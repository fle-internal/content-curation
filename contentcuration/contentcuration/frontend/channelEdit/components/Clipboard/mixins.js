import { mapActions, mapGetters } from 'vuex';
import { SelectionFlags } from 'frontend/channelEdit/vuex/clipboard/constants';

export default {
  props: {
    nodeId: {
      type: String,
      required: true,
    },
    ancestorId: {
      type: String,
      default: null,
    },
    level: {
      type: Number,
      default: 0,
    },
  },
  computed: {
    ...mapGetters('clipboard', [
      'getClipboardNodeForRender',
      'getSelectionState',
      'getNextSelectionState',
      'getClipboardChildren',
    ]),
    contentNode() {
      return this.nodeId ? this.getClipboardNodeForRender(this.nodeId) : null;
    },
    indentPadding() {
      return `${this.level * 32}px`;
    },
    selectionState() {
      return this.getSelectionState(this.nodeId, this.ancestorId);
    },
    nextSelectionState() {
      return this.getNextSelectionState(this.nodeId, this.ancestorId);
    },
    selected() {
      return Boolean(this.selectionState & SelectionFlags.SELECTED);
    },
    indeterminate() {
      return Boolean(this.selectionState & SelectionFlags.INDETERMINATE);
    },
  },
  methods: {
    ...mapActions('clipboard', ['setSelectionState', 'resetSelectionState']),
    goNextSelectionState() {
      this.setSelectionState({
        id: this.nodeId,
        selectionState: this.nextSelectionState,
        ancestorId: this.ancestorId,
      });
    },
  },
};

export const parentMixin = {
  props: {
    nodeId: {
      type: String,
      required: true,
    },
    ancestorId: {
      type: String,
      default: null,
    },
    level: {
      type: Number,
      default: 0,
    },
  },
  computed: {
    ...mapGetters('clipboard', [
      'channelIds',
      'getClipboardChildren',
      'hasClipboardChildren',
      'isClipboardNode',
    ]),
    children() {
      return this.getClipboardChildren(this.nodeId, this.ancestorId);
    },
  },
  methods: {
    ...mapActions('clipboard', ['loadClipboardNodes']),
  },
};
