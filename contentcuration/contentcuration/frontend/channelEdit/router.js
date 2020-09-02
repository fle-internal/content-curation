import VueRouter from 'vue-router';
import { RouterNames } from './constants';
import TreeView from './views/TreeView';
import StagingTreePage from './pages/StagingTreePage';
import store from './store';
import AddPreviousStepsPage from './pages/AddPreviousStepsPage';
import AddNextStepsPage from './pages/AddNextStepsPage';
import TrashModal from './views/trash/TrashModal';
import SearchOrBrowseWindow from './views/ImportFromChannels/SearchOrBrowseWindow';
import ReviewSelectionsPage from './views/ImportFromChannels/ReviewSelectionsPage';
import EditModal from './components/edit/EditModal';
import { RouterNames as ChannelRouterNames } from 'frontend/channelList/constants';
import Sandbox from 'shared/views/Sandbox';
import ChannelModal from 'shared/views/channel/ChannelModal';
import ChannelDetailsModal from 'shared/views/channel/ChannelDetailsModal';

const router = new VueRouter({
  routes: [
    {
      name: RouterNames.SANDBOX,
      path: '/sandbox/:nodeId',
      props: true,
      component: Sandbox,
      beforeEnter: (to, from, next) => {
        const channelPromise = store.dispatch('currentChannel/loadChannel');
        const treePromise = store.dispatch(
          'contentNode/loadTree',
          store.state.currentChannel.currentChannelId
        );
        const nodePromise = store.dispatch('contentNode/loadContentNode', to.params.nodeId);
        // api call to get ancestors if nodeId is a child descendant???
        return Promise.all([channelPromise, treePromise, nodePromise])
          .then(() => next())
          .catch(() => {});
      },
    },
    {
      name: RouterNames.TREE_ROOT_VIEW,
      path: '/',
      beforeEnter: (to, from, next) => {
        return store.dispatch('currentChannel/loadChannel').then(channel => {
          const nodeId = channel.root_id;
          return next({
            name: RouterNames.TREE_VIEW,
            params: {
              nodeId,
            },
            replace: true,
          });
        });
      },
    },
    {
      name: RouterNames.IMPORT_FROM_CHANNELS_BROWSE,
      path: '/import/:destNodeId/browse/:channelId?/:nodeId?',
      component: SearchOrBrowseWindow,
      props: true,
    },
    {
      name: RouterNames.IMPORT_FROM_CHANNELS_SEARCH,
      path: '/import/:destNodeId/search/:searchTerm',
      component: SearchOrBrowseWindow,
      props: true,
    },
    {
      name: RouterNames.IMPORT_FROM_CHANNELS_REVIEW,
      path: '/import/:destNodeId/review',
      component: ReviewSelectionsPage,
      props: true,
    },
    {
      name: RouterNames.STAGING_TREE_VIEW,
      path: '/staging/:nodeId/:detailNodeId?',
      props: true,
      component: StagingTreePage,
      beforeEnter: (to, from, next) => {
        return store
          .dispatch('currentChannel/loadChannel', { staging: true })
          .then(channel => {
            if (channel.staging_root_id) {
              return store.dispatch('contentNode/loadTree', { tree_id: channel.staging_root_id });
            }
          })
          .catch(error => {
            throw new Error(error);
          })
          .then(() => next());
      },
    },
    {
      name: RouterNames.ADD_PREVIOUS_STEPS,
      path: '/previous-steps/:nodeId',
      props: true,
      component: AddPreviousStepsPage,
      beforeEnter: (to, from, next) => {
        const { currentChannelId } = store.state.currentChannel;
        const { nodeId } = to.params;
        const promises = [
          store.dispatch('channel/loadChannel', currentChannelId),
          store.dispatch('contentNode/loadRelatedResources', nodeId),
        ];

        return Promise.all(promises)
          .catch(error => {
            throw new Error(error);
          })
          .then(() => next());
      },
    },
    {
      name: RouterNames.ADD_NEXT_STEPS,
      path: '/next-steps/:nodeId',
      props: true,
      component: AddNextStepsPage,
      beforeEnter: (to, from, next) => {
        const { currentChannelId } = store.state.currentChannel;
        const { nodeId } = to.params;
        const promises = [
          store.dispatch('channel/loadChannel', currentChannelId),
          store.dispatch('contentNode/loadRelatedResources', nodeId),
        ];

        return Promise.all(promises)
          .catch(error => {
            throw new Error(error);
          })
          .then(() => next());
      },
    },
    {
      name: RouterNames.TRASH,
      path: '/:nodeId/:detailNodeId?/trash',
      component: TrashModal,
      props: true,
      beforeEnter: (to, from, next) => {
        return store
          .dispatch('currentChannel/loadChannel')
          .catch(error => {
            throw new Error(error);
          })
          .then(() => next());
      },
    },
    {
      name: ChannelRouterNames.CHANNEL_DETAILS,
      path: '/:nodeId/:detailNodeId?/channel/:channelId/details',
      component: ChannelDetailsModal,
      props: true,
      beforeEnter: (to, from, next) => {
        return store
          .dispatch('currentChannel/loadChannel')
          .catch(error => {
            throw new Error(error);
          })
          .then(() => next());
      },
    },
    {
      name: ChannelRouterNames.CHANNEL_EDIT,
      path: '/:nodeId/:detailNodeId?/channel/:channelId/edit',
      component: ChannelModal,
      props: true,
      beforeEnter: (to, from, next) => {
        return store
          .dispatch('currentChannel/loadChannel')
          .catch(error => {
            throw new Error(error);
          })
          .then(() => next());
      },
    },
    {
      name: RouterNames.CONTENTNODE_DETAILS,
      path: '/:nodeId/:detailNodeId?/details/:detailNodeIds/:tab?',
      props: true,
      component: EditModal,
      beforeEnter: (to, from, next) => {
        return store
          .dispatch('currentChannel/loadChannel')
          .catch(error => {
            throw new Error(error);
          })
          .then(() => next());
      },
    },
    {
      name: RouterNames.ADD_TOPICS,
      path: '/:nodeId/:detailNodeId?/topics/:detailNodeIds/:tab?',
      props: true,
      component: EditModal,
      beforeEnter: (to, from, next) => {
        return store
          .dispatch('currentChannel/loadChannel')
          .catch(error => {
            throw new Error(error);
          })
          .then(() => next());
      },
    },
    {
      name: RouterNames.ADD_EXERCISE,
      path: '/:nodeId/:detailNodeId?/exercise/:detailNodeIds/:tab?',
      props: true,
      component: EditModal,
      beforeEnter: (to, from, next) => {
        return store
          .dispatch('currentChannel/loadChannel')
          .catch(error => {
            throw new Error(error);
          })
          .then(() => next());
      },
    },
    {
      name: RouterNames.UPLOAD_FILES,
      path: '/:nodeId/:detailNodeId?/upload/:detailNodeIds?/:tab?',
      props: true,
      component: EditModal,
      beforeEnter: (to, from, next) => {
        return store
          .dispatch('currentChannel/loadChannel')
          .catch(error => {
            throw new Error(error);
          })
          .then(() => next());
      },
    },
    {
      name: RouterNames.TREE_VIEW,
      path: '/:nodeId/:detailNodeId?',
      props: true,
      component: TreeView,
      beforeEnter: (to, from, next) => {
        const { currentChannelId } = store.state.currentChannel;

        return store
          .dispatch('currentChannel/loadChannel')
          .then(() => {
            return store.dispatch('contentNode/loadChannelTree', currentChannelId);
          })
          .catch(error => {
            throw new Error(error);
          })
          .then(() => next());
      },
    },
  ],
});

export default router;
