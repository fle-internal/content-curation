import * as getters from './getters';
import * as actions from './actions';
import * as mutations from './mutations';
import persistFactory from 'shared/vuex/persistFactory';
import { TABLE_NAMES, CHANGE_TYPES } from 'shared/data';

export default {
  namespaced: true,
  state: () => ({
    /**
     * A map of node/channel/clipboard-root ID => Selection State, a bitmask of selection flags
     *
     * Selection flags (constants.js):
     *  NONE, SELECTED, INDETERMINATE, ALL_DESCENDANTS
     */
    selected: {},

    /**
     * A map of channel ID => color
     *
     * These are persisted in local storage through the persist plugin
     */
    channelColors: {},

    /**
     * A local map of channel ID => channel
     *
     * Having a local copy of this helps prevent a circular lookup issue
     * in the selection state management
     */
    channelMap: {},
    /**
     * A map of clipboard node ID => clipboard node
     *
     */
    clipboardNodesMap: {},
    // Temporary state to store data about clipboard nodes for moving in the move modal
    clipboardMoveNodes: [],
  }),
  getters,
  actions,
  mutations,
  plugins: [persistFactory('clipboard', ['ADD_CHANNEL_COLOR'])],
  listeners: {
    [TABLE_NAMES.CLIPBOARD]: {
      [CHANGE_TYPES.CREATED]: 'ADD_CLIPBOARD_NODE',
      [CHANGE_TYPES.DELETED]: 'REMOVE_CLIPBOARD_NODE',
    },
  },
};
