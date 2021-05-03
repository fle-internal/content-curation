import debounce from 'lodash/debounce';
import get from 'lodash/get';
import pick from 'lodash/pick';
import applyChanges from './applyRemoteChanges';
import { createChannel } from './broadcastChannel';
import { hasActiveLocks, cleanupLocks } from './changes';
import {
  CHANGE_LOCKS_TABLE,
  CHANGE_TYPES,
  CHANGES_TABLE,
  IGNORED_SOURCE,
  MESSAGES,
  STATUS,
  CHANNEL_SYNC_KEEP_ALIVE_INTERVAL,
} from './constants';
import db from './db';
import mergeAllChanges from './mergeChanges';
import { API_RESOURCES, INDEXEDDB_RESOURCES } from './registry';
import { Session } from './resources';
import client from 'shared/client';
import urls from 'shared/urls';

// When this many seconds pass without a syncable
// change being registered, sync changes!
const SYNC_IF_NO_CHANGES_FOR = 2;

// Interval at which to check for new changes
const SYNC_INTERVAL = 5;

// In order to listen to messages being sent
// by all windows, including this one, for requests
// to fetch collections or models, we have to create
// a new channel instance, rather than using the one
// already instantiated in the broadcastChannel module.
const channel = createChannel();

// Stores last setTimeout in polling so we may clear it when we want
let unsyncedPollingTimeoutId;

// Flag to check if a sync is currently active.
let syncActive = false;

function handleFetchMessages(msg) {
  if (msg.type === MESSAGES.FETCH_COLLECTION && msg.urlName && msg.params) {
    API_RESOURCES[msg.urlName]
      .fetchCollection(msg.params)
      .then(data => {
        channel.postMessage({
          messageId: msg.messageId,
          type: MESSAGES.REQUEST_RESPONSE,
          status: STATUS.SUCCESS,
          data,
        });
      })
      .catch(err => {
        try {
          JSON.stringify(err);
        } catch (e) {
          // If can't convert err to JSON, postMessage will break
          err = err.toString();
        }
        channel.postMessage({
          messageId: msg.messageId,
          type: MESSAGES.REQUEST_RESPONSE,
          status: STATUS.FAILURE,
          err,
        });
      });
  }
  if (msg.type === MESSAGES.FETCH_MODEL && msg.urlName && msg.id) {
    API_RESOURCES[msg.urlName]
      .fetchModel(msg.id)
      .then(data => {
        channel.postMessage({
          messageId: msg.messageId,
          type: MESSAGES.REQUEST_RESPONSE,
          status: STATUS.SUCCESS,
          data,
        });
      })
      .catch(err => {
        channel.postMessage({
          messageId: msg.messageId,
          type: MESSAGES.REQUEST_RESPONSE,
          status: STATUS.FAILURE,
          err,
        });
      });
  }
}

function startChannelFetchListener() {
  channel.addEventListener('message', handleFetchMessages);
}

function stopChannelFetchListener() {
  channel.removeEventListener('message', handleFetchMessages);
}

const channelsToSync = {};

function handleChannelSyncMessages(msg) {
  if (msg.type === MESSAGES.SYNC_CHANNEL && msg.channelId) {
    channelsToSync[msg.channelId] = Date.now();
  }
}

function startChannelSyncListener() {
  channel.addEventListener('message', handleChannelSyncMessages);
}

function stopChannelSyncListener() {
  channel.removeEventListener('message', handleChannelSyncMessages);
}

function isSyncableChange(change) {
  const src = change.source || '';

  return (
    !src.match(IGNORED_SOURCE) &&
    INDEXEDDB_RESOURCES[change.table] &&
    INDEXEDDB_RESOURCES[change.table].syncable
  );
}

function applyResourceListener(change) {
  const resource = INDEXEDDB_RESOURCES[change.table];
  if (resource && resource.listeners && resource.listeners[change.type]) {
    resource.listeners[change.type](change);
  }
}

const commonFields = ['type', 'key', 'table', 'rev', 'channel_id', 'user_id'];
const createFields = commonFields.concat(['obj']);
const updateFields = commonFields.concat(['mods']);
const movedFields = commonFields.concat(['target', 'position']);
const copiedFields = commonFields.concat([
  'from_key',
  'mods',
  'target',
  'position',
  'excluded_descendants',
]);

function trimChangeForSync(change) {
  if (change.type === CHANGE_TYPES.CREATED) {
    return pick(change, createFields);
  } else if (change.type === CHANGE_TYPES.UPDATED) {
    return pick(change, updateFields);
  } else if (change.type === CHANGE_TYPES.DELETED) {
    return pick(change, commonFields);
  } else if (change.type === CHANGE_TYPES.MOVED) {
    return pick(change, movedFields);
  } else if (change.type === CHANGE_TYPES.COPIED) {
    return pick(change, copiedFields);
  }
}

function handleDisallowed(response) {
  // The disallowed property is an array of any changes that were sent to the server,
  // that were rejected.
  const disallowed = get(response, ['data', 'disallowed'], []);
  if (disallowed.length) {
    // Collect all disallowed
    const disallowedRevs = disallowed.map(d => d.rev);
    // Set the return error data onto the changes - this will update the change
    // both with any errors and the results of any merging that happened prior
    // to the sync operation being called
    return db[CHANGES_TABLE].where('rev')
      .anyOf(disallowedRevs.map(Number))
      .modify({ disallowed: true, synced: true });
  }
  return Promise.resolve();
}

function handleAllowed(response) {
  // The allowed property is an array of any rev and server_rev for any changes sent to
  // the server that were accepted
  const allowed = get(response, ['data', 'allowed'], []);
  if (allowed.length) {
    const revMap = {};
    for (let obj of allowed) {
      revMap[obj.rev] = obj.server_rev;
    }
    return db[CHANGES_TABLE].where('rev')
      .anyOf(Object.keys(revMap).map(Number))
      .modify(c => {
        c.server_rev = revMap[c.rev];
        c.synced = true;
      });
  }
  return Promise.resolve();
}

function handleReturnedChanges(response) {
  // The changes property is an array of any changes from the server to apply in the
  // client.
  const returnedChanges = get(response, ['data', 'changes'], []);
  if (returnedChanges.length) {
    return applyChanges(returnedChanges);
  }
  return Promise.resolve();
}

function handleErrors(response) {
  // The errors property is an array of any changes that were sent to the server,
  // that were rejected, with an additional errors property that describes
  // the error.
  const errors = get(response, ['data', 'errors'], []);
  if (errors.length) {
    const errorMap = {};
    for (let error of errors) {
      errorMap[error.rev] = error;
    }
    // Set the return error data onto the changes - this will update the change
    // both with any errors and the results of any merging that happened prior
    // to the sync operation being called
    return db[CHANGES_TABLE].where('rev')
      .anyOf(Object.keys(errorMap).map(Number))
      .modify(obj => {
        return Object.assign(obj, errorMap[obj.rev]);
      });
  }
  return Promise.resolve();
}

function handleSuccesses(response) {
  // The successes property is an array of server_revs for any previously synced changes
  // that have now been successfully applied on the server.
  const successes = get(response, ['data', 'successes'], []);
  if (successes.length) {
    return db[CHANGES_TABLE].where('server_rev')
      .anyOf(successes)
      .delete();
  }
  return Promise.resolve();
}

function handleMaxRev(response) {
  const max_rev = response.data.max_rev;
  return Session.updateSession({ max_rev });
}

async function syncChanges() {
  // Note: we could in theory use Dexie syncable for what
  // we are doing here, but I can't find a good way to make
  // it ignore our regular API calls for seeding the database
  // Also, the pattern it expects for server interactions would
  // require greater backend rearchitecting to focus our server-client
  // interactions on changes to objects, with consistent and resolvable
  // revisions. We will do this for now, but we have the option of doing
  // something more involved and better architectured in the future.

  syncActive = true;

  // Track the maxRevision at this moment so that we can ignore any changes that
  // might have come in during processing - leave them for the next cycle.
  // This is the primary key of the change objects, so the collection is ordered by this
  // by default - if we just grab the last object, we can get the key from there.
  const [lastChange, earliestServerChange, user] = await Promise.all([
    db[CHANGES_TABLE].orderBy('rev').last(),
    db[CHANGES_TABLE].orderBy('server_rev').first(),
    Session.getSession(),
  ]);
  if (!user) {
    // If not logged in, nothing to do.
    return;
  }
  const now = Date.now();
  const channel_ids = Object.entries(channelsToSync)
    .filter(([id, time]) => id && time > now - CHANNEL_SYNC_KEEP_ALIVE_INTERVAL)
    .map(([id]) => id);
  const requestPayload = {
    changes: [],
    channel_ids,
    // Last rev to send to the server is either the earliest change we are still seeking
    // confirmation on, or the current max_rev that we have synced to the frontend.
    last_rev: (earliestServerChange && earliestServerChange.server_rev) || user.max_rev,
  };

  if (lastChange) {
    const changesMaxRevision = lastChange.rev;
    const syncableChanges = db[CHANGES_TABLE].where('rev')
      .belowOrEqual(changesMaxRevision)
      .filter(c => !c.synced);
    const changesToSync = await syncableChanges.toArray();
    // By the time we get here, our changesToSync Array should
    // have every change we want to sync to the server, so we
    // can now trim it down to only what is needed to transmit over the wire.
    // TODO: remove moves when a delete change is present for an object,
    // because a delete will wipe out the move.
    const changes = changesToSync.map(trimChangeForSync);
    // Create a promise for the sync - if there is nothing to sync just resolve immediately,
    // in order to still call our change cleanup code.
    if (changes.length) {
      requestPayload.changes = changes;
    }
  }
  try {
    // The response from the sync endpoint has the format:
    // {
    //   "disallowed": [],
    //   "allowed": [],
    //   "changes": [],
    //   "errors": [],
    //   "successess": [],
    // }
    const response = await client.post(urls['sync'](), requestPayload);
    try {
      await Promise.all([
        handleDisallowed(response),
        handleAllowed(response),
        handleReturnedChanges(response),
        handleErrors(response),
        handleSuccesses(response),
        handleMaxRev(response),
      ]);
    } catch (err) {
      console.error('There was an error updating change status', err); // eslint-disable-line no-console
    }
  } catch (err) {
    // There was an error during syncing, log, but carry on
    console.warn('There was an error during syncing with the backend for', err); // eslint-disable-line no-console
  }
  syncActive = false;
}

const debouncedSyncChanges = debounce(() => {
  return hasActiveLocks().then(hasLocks => {
    if (!hasLocks && !syncActive) {
      return syncChanges();
    }
  });
}, SYNC_IF_NO_CHANGES_FOR * 1000);

if (process.env.NODE_ENV !== 'production' && typeof window !== 'undefined') {
  window.forceServerSync = forceServerSync;

  window.stopPollingUnsyncedChanges = stopPollingUnsyncedChanges;
  window.pollUnsyncedChanges = pollUnsyncedChanges;
}

async function handleChanges(changes) {
  changes.map(applyResourceListener);
  const syncableChanges = changes.filter(isSyncableChange);

  const lockChanges = changes.find(
    change => change.table === CHANGE_LOCKS_TABLE && change.type === CHANGE_TYPES.DELETED
  );

  if (syncableChanges.length) {
    // Flatten any changes before we store them in the changes table
    const mergedSyncableChanges = mergeAllChanges(syncableChanges, true).map(change => {
      // Filter out the rev property as we want that to be assigned during the bulkPut
      const { rev, ...filteredChange } = change; // eslint-disable-line no-unused-vars
      // Set appropriate contextual information on changes, channel_id and user_id
      INDEXEDDB_RESOURCES[change.table].setChannelIdOnChange(filteredChange);
      INDEXEDDB_RESOURCES[change.table].setUserIdOnChange(filteredChange);
      return filteredChange;
    });

    await db[CHANGES_TABLE].bulkPut(mergedSyncableChanges);
  }

  // If we detect locks were removed, or changes were written to the changes table
  // then we'll trigger sync
  if (lockChanges || syncableChanges.length) {
    debouncedSyncChanges();
  }
}

async function pollUnsyncedChanges() {
  await debouncedSyncChanges();
  unsyncedPollingTimeoutId = setTimeout(() => pollUnsyncedChanges(), SYNC_INTERVAL * 1000);
}

function stopPollingUnsyncedChanges() {
  if (unsyncedPollingTimeoutId) {
    clearTimeout(unsyncedPollingTimeoutId);
  }
}

export function startSyncing() {
  startChannelFetchListener();
  startChannelSyncListener();
  cleanupLocks();
  // Initiate a sync immediately in case any data
  // is left over in the database.
  debouncedSyncChanges();
  // Begin polling our CHANGES_TABLE
  pollUnsyncedChanges();
  db.on('changes', handleChanges);
}

export function stopSyncing() {
  stopChannelFetchListener();
  stopChannelSyncListener();
  debouncedSyncChanges.cancel();
  // Stop pollUnsyncedChanges
  stopPollingUnsyncedChanges();
  // Dexie's slightly counterintuitive method for unsubscribing from events
  db.on('changes').unsubscribe(handleChanges);
}

export function forceServerSync() {
  debouncedSyncChanges();
  return debouncedSyncChanges.flush();
}
