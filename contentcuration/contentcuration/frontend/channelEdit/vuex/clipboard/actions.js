import get from 'lodash/get';
import uniq from 'lodash/uniq';
import uniqBy from 'lodash/uniqBy';
import * as Vibrant from 'node-vibrant';
import { SelectionFlags } from './constants';
import { selectionId } from './utils';
import { promiseChunk } from 'shared/utils/helpers';
import { Clipboard } from 'shared/data/resources';

export function loadChannels(context) {
  const clipboardRootId = context.rootGetters['clipboardRootId'];
  return Clipboard.where({ parent: clipboardRootId }).then(clipboardNodes => {
    if (!clipboardNodes.length) {
      return [];
    }

    const root = true;

    // Find the channels we need to load
    const channelIds = uniq(
      clipboardNodes.map(clipboardNode => clipboardNode.source_channel_id).filter(Boolean)
    );
    const nodeIdChannelIdPairs = uniqBy(
      clipboardNodes,
      c => c.source_node_id + c.source_channel_id
    ).map(c => [c.source_node_id, c.source_channel_id]);
    return Promise.all([
      promiseChunk(channelIds, 50, id__in => {
        // Load up the source channels
        return context.dispatch('channel/loadChannelList', { id__in }, { root });
      }),
      context.dispatch(
        'contentNode/loadContentNodes',
        { '[node_id+channel_id]__in': nodeIdChannelIdPairs },
        { root }
      ),
    ]).then(([channels]) => {
      // Add the channel to the selected state, it acts like a node
      channels.forEach(channel => {
        if (!(channel.id in context.state.selected)) {
          context.commit('UPDATE_SELECTION_STATE', {
            id: channel.id,
            selectionState: SelectionFlags.NONE,
          });
        }
      });

      // Be sure to put these in after the channels!
      clipboardNodes.forEach(node => {
        if (!(node.id in context.state.selected)) {
          context.commit('UPDATE_SELECTION_STATE', {
            id: node.id,
            selectionState: SelectionFlags.NONE,
          });
        }
      });

      // Do not return dispatch, let this operate async
      context.dispatch('loadChannelColors');
      context.commit('ADD_CLIPBOARD_NODES', clipboardNodes);
      return clipboardNodes;
    });
  });
}

export function loadClipboardNodes(context, { parent, ancestorId }) {
  const parentNode = context.state.clipboardNodesMap[parent];
  const root = true;
  if (parentNode && parentNode.total_resources) {
    return Clipboard.where({ parent }).then(clipboardNodes => {
      if (!clipboardNodes.length) {
        return [];
      }

      const nodeIdChannelIdPairs = uniqBy(
        clipboardNodes,
        c => c.source_node_id + c.source_channel_id
      ).map(c => [c.source_node_id, c.source_channel_id]);
      return context
        .dispatch(
          'contentNode/loadContentNodes',
          { '[node_id+channel_id]__in': nodeIdChannelIdPairs },
          { root }
        )
        .then(() => {
          // Be sure to put these in after the channels!
          clipboardNodes.forEach(node => {
            if (!(node.id in context.state.selected)) {
              context.commit('UPDATE_SELECTION_STATE', {
                id: node.id,
                selectionState: SelectionFlags.NONE,
              });
            }
          });

          context.commit('ADD_CLIPBOARD_NODES', clipboardNodes);
          return clipboardNodes;
        });
    });
  } else {
    // Has no child resources, so fetch children of associated contentnode instead
    const contentNode = context.getters.getClipboardNodeForRender(parent);
    if (contentNode) {
      return context
        .dispatch('contentNode/loadContentNodes', { parent: contentNode.id }, { root })
        .then(contentNodes => {
          // Be sure to put these in after the channels!
          contentNodes.forEach(node => {
            if (!(node.id in context.state.selected)) {
              context.commit('UPDATE_SELECTION_STATE', {
                id: node.id,
                selectionState: SelectionFlags.NONE,
                ancestorId,
              });
            }
          });
          return [];
        });
    }
  }
  return [];
}

// Here are the swatches Vibrant gives, and the order we'll check them for colors we can use.
const colorChoiceOrder = [
  'Vibrant',
  'LightVibrant',
  'DarkVibrant',
  'LightMuted',
  'Muted',
  'DarkMuted',
];

export function loadChannelColors(context) {
  const channels = context.getters.channels;

  // Reducing the channels, going one by one processing colors, and collection an array
  // of all of them
  return channels.reduce((promise, channel) => {
    const src = channel.thumbnail_encoding['base64']
      ? channel.thumbnail_encoding['base64']
      : channel.thumbnail_url;

    // If we already have the color, just no src, then we'll just skip
    if (context.getters.getChannelColor(channel.id, null) !== null || !src) {
      return promise;
    }

    const image = new Image();
    image.src = src;

    //
    return promise.then(allColors => {
      return Vibrant.from(image)
        .getPalette()
        .then(palette => {
          let color = null;

          if (palette) {
            const colors = colorChoiceOrder.map(name => palette[name].getHex());
            // Find the first color that we don't already have
            color = colors.find(color => !allColors.includes(color)) || color;
            allColors.push(color);
          }

          // Add it now so the user can see it
          context.commit('ADD_CHANNEL_COLOR', { id: channel.id, color });
          return allColors;
        });
    });
  }, Promise.resolve(Object.values(context.state.channelColors)));
}

/**
 * @param context
 * @param {string} node_id
 * @param {string} channel_id
 * @param {string|null} [target]
 * @param {boolean} [deep]
 * @param children
 * @return {*}
 */
export function copy(
  context,
  { node_id, channel_id, children = [], parent = null, extra_fields = null }
) {
  const clipboardRootId = context.rootGetters['clipboardRootId'];

  // This copies a "bare" copy, if you want a full content node copy,
  // go to the contentNode state actions
  return Clipboard.copy(node_id, channel_id, clipboardRootId, parent, extra_fields).then(node => {
    if (!children.length) {
      // Refresh our channel list following the copy
      context.dispatch('loadChannels');
      return [node];
    }

    return promiseChunk(children, 1, ([child]) => {
      return context.dispatch(
        'copy',
        Object.assign(child, {
          parent: node.id,
        })
      );
    })
      .then(otherNodes => {
        // Add parent to beginning
        otherNodes.unshift(node);
        // Refresh our channel list following the copy
        context.dispatch('loadChannels');
        return otherNodes;
      })
      .then(nodes => {
        context.commit('ADD_CLIPBOARD_NODES', nodes);
      });
  });
}

/*
 * For convenience, this function takes an array of nodes as the argument,
 * to consolidate any uniquefying.
 */
export function copyAll(context, { nodes }) {
  const sources = uniqBy(nodes, c => c.node_id + c.channel_id)
    .map(n => ({ node_id: n.node_id, channel_id: n.channel_id }))
    .filter(n => n.node_id && n.channel_id);
  return promiseChunk(sources, 20, sourcesChunk => {
    return Promise.all(sourcesChunk.map(source => context.dispatch('copy', source)));
  });
}

/**
 * Recursive function to set selection state for a node, and possibly it's ancestors and descendants
 */
export function setSelectionState(
  context,
  { id, selectionState, deep = true, parents = true, ancestorId = null }
) {
  const currentState = context.state.selected[selectionId(id, ancestorId)];

  // Well, we should only bother if it needs updating
  if (currentState !== selectionState) {
    context.commit('UPDATE_SELECTION_STATE', { id, selectionState, ancestorId });
  } else if (!deep && !parents) {
    return;
  }

  // Union for the ALL state (5)
  const ALL = SelectionFlags.SELECTED | SelectionFlags.ALL_DESCENDANTS;

  // Does this change cascade to the children? If so, and we're going `deep` then
  // cascade down what should happen
  if (deep && (!(selectionState & SelectionFlags.INDETERMINATE) || currentState > ALL)) {
    const clipboardTreeId = context.rootGetters['clipboardRootId'];
    const children =
      id === clipboardTreeId
        ? context.getters.channelIds
        : context.getters.getClipboardChildren(id, ancestorId).map(c => c.id);
    // Update descendants
    children.forEach(cid => {
      context.dispatch('setSelectionState', {
        id: cid,
        selectionState: selectionState === ALL ? ALL : SelectionFlags.NONE,
        parents: false,
        ancestorId: context.getters.isClipboardNode(cid)
          ? null
          : context.getters.isClipboardNode(id)
          ? id
          : ancestorId,
      });
    });
  }

  const parentId = context.getters.getClipboardParentId(id, ancestorId);

  if (parentId && parents) {
    // Updating the parents at this point is fairly easy, we just recurse upwards, recomputing
    // the new state for the parent
    const parentAncestorId = ancestorId === parentId ? null : ancestorId;
    context.dispatch('setSelectionState', {
      id: parentId,
      selectionState: context.getters.getSelectionState(parentId, parentAncestorId),
      deep: false,
      ancestorId: parentAncestorId,
    });
  }
}

/**
 * Global deselect all!
 */
export function resetSelectionState(context) {
  const clipboardTreeId = context.rootGetters['clipboardRootId'];
  return context.dispatch('setSelectionState', {
    id: clipboardTreeId,
    selectionState: SelectionFlags.NONE,
    deep: true,
  });
}

export function deleteClipboardNode(context, { clipboardNodeId, ancestorId = null }) {
  if (context.getters.isClipboardNode(clipboardNodeId)) {
    return Clipboard.delete(clipboardNodeId).then(() => {
      context.commit('REMOVE_CLIPBOARD_NODE', { id: clipboardNodeId });
    });
  }
  const ancestor = context.state.clipboardNodesMap[ancestorId];
  const excluded_descendants = {
    ...get(ancestor, ['extra_fields', 'excluded_descendants'], {}),
    [clipboardNodeId]: true,
  };
  const update = {
    extra_fields: {
      excluded_descendants,
    },
  };
  // Otherwise we have a non clipboard node
  return Clipboard.update(ancestorId).then(() => {
    context.commit('ADD_CLIPBOARD_NODE', {
      ...ancestor,
      ...update,
    });
  });
}

export function deleteClipboardNodes(context, selectionIds) {
  return Promise.all(
    selectionIds.map(selectionId => {
      return deleteClipboardNode(context, {
        clipboardNodeId: selectionId.split('-')[0],
        ancestorId: selectionId.split('-')[1],
      });
    })
  );
}
