import pick from 'lodash/pick';
import { ContentDefaults } from 'shared/constants';
import { Channel } from 'shared/data/resources';

/* CHANNEL LIST ACTIONS */
export function loadChannelList(context, payload = {}) {
  if (payload.listType) {
    payload[payload.listType] = true;
    delete payload.listType;
  }
  const params = {
    // Default to getting not deleted channels
    deleted: false,
    ...payload,
  };
  return Channel.where(params).then(channels => {
    context.commit('ADD_CHANNELS', channels);
    return channels;
  });
}

export function loadChannel(context, id) {
  return Channel.get(id)
    .then(channel => {
      context.commit('ADD_CHANNEL', channel);
      return channel;
    })
    .catch(() => {
      return;
    });
}

/* CHANNEL EDITOR ACTIONS */

export function createChannel(context) {
  const session = context.rootState.session;
  const channelData = {
    name: '',
    description: '',
    language: session.preferences ? session.preferences.language : session.currentLanguage,
    content_defaults: session.preferences,
    thumbnail_url: '',
    bookmark: false,
    edit: true,
    deleted: false,
  };
  return Channel.put(channelData).then(id => {
    context.commit('ADD_CHANNEL', {
      id,
      ...channelData,
    });
    return id;
  });
}

export function updateChannel(context, { id, name = null, description = null, thumbnailData = null, language = null, contentDefaults = null } = {}) {
  const channelData = {};
  if (!id) {
    throw ReferenceError('id must be defined to update a channel');
  }
  if (name !== null) {
    channelData.name = name;
  }
  if (description !== null) {
    channelData.description = description;
  }
  if (
    thumbnailData !== null &&
    ['thumbnail', 'thumbnail_url', 'thumbnail_encoding'].every(attr => thumbnailData[attr])
  ) {
    channelData.thumbnail = thumbnailData.thumbnail;
    channelData.thumbnail_url = thumbnailData.thumbnail_url;
    channelData.thumbnail_encoding = thumbnailData.thumbnail_encoding;
  }
  if (language !== null) {
    channelData.language = language;
  }
  if (contentDefaults !== null) {
    channelData.content_defaults = {};
    // Assign all acceptable content defaults into the channel defaults
    Object.assign(
      channelData.content_defaults,
      pick(contentDefaults, Object.keys(ContentDefaults)),
    );
  }
  context.commit('UPDATE_CHANNEL', { id, ...channelData });
  return Channel.update(id, channelData);
}

export function bookmarkChannel(context, { id, bookmark }) {
  return Channel.update(id, { bookmark }).then(() => {
    context.commit('SET_BOOKMARK', { id, bookmark });
  });
}

export function deleteChannel(context, channelId) {
  return Channel.update(channelId, { deleted: true }).then(() => {
    context.commit('REMOVE_CHANNEL', { id: channelId });
  });
}