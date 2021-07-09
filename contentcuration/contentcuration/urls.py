"""URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/1.8/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  re_path(r'^$', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  re_path(r'^$', Home.as_view(), name='home')
Including another URLconf
    1. Add an import:  from blog import urls as blog_urls
    2. Add a URL to urlpatterns:  re_path(r'^blog/', include(blog_urls))
"""
import django_js_reverse.views as django_js_reverse_views
from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.urls import include
from django.urls import re_path
from django.views.generic.base import RedirectView
from rest_framework import routers

import contentcuration.views.admin as admin_views
import contentcuration.views.base as views
import contentcuration.views.internal as internal_views
import contentcuration.views.nodes as node_views
import contentcuration.views.public as public_views
import contentcuration.views.settings as settings_views
import contentcuration.views.users as registration_views
import contentcuration.views.zip as zip_views
from contentcuration.views import pwa
from contentcuration.viewsets.assessmentitem import AssessmentItemViewSet
from contentcuration.viewsets.channel import AdminChannelViewSet
from contentcuration.viewsets.channel import CatalogViewSet
from contentcuration.viewsets.channel import ChannelViewSet
from contentcuration.viewsets.channelset import ChannelSetViewSet
from contentcuration.viewsets.clipboard import ClipboardViewSet
from contentcuration.viewsets.contentnode import ContentNodeViewSet
from contentcuration.viewsets.file import FileViewSet
from contentcuration.viewsets.invitation import InvitationViewSet
from contentcuration.viewsets.sync.endpoint import sync
from contentcuration.viewsets.task import TaskViewSet
from contentcuration.viewsets.user import AdminUserViewSet
from contentcuration.viewsets.user import ChannelUserViewSet
from contentcuration.viewsets.user import UserViewSet


class StagingPageRedirectView(RedirectView):
    def get_redirect_url(self, *args, **kwargs):
        channel_id = kwargs['channel_id']
        return '/channels/{}/#/staging'.format(channel_id)


router = routers.DefaultRouter(trailing_slash=False)
router.register(r'channel', ChannelViewSet)
router.register(r'channelset', ChannelSetViewSet)
router.register(r'catalog', CatalogViewSet, basename='catalog')
router.register(r'admin-channels', AdminChannelViewSet, basename='admin-channels')
router.register(r'file', FileViewSet)
router.register(r'task', TaskViewSet)
router.register(r'channeluser', ChannelUserViewSet, basename="channeluser")
router.register(r'user', UserViewSet)
router.register(r'invitation', InvitationViewSet)
router.register(r'contentnode', ContentNodeViewSet)
router.register(r'assessmentitem', AssessmentItemViewSet)
router.register(r'admin-users', AdminUserViewSet, basename='admin-users')
router.register(r'clipboard', ClipboardViewSet, basename='clipboard')

urlpatterns = [
    re_path(r'^api/', include(router.urls)),
    re_path(r'^serviceWorker.js$', pwa.ServiceWorkerView.as_view(), name="service_worker"),
    re_path(r'^api/activate_channel$', views.activate_channel_endpoint, name='activate_channel'),
    re_path(r'^healthz$', views.health, name='health'),
    re_path(r'^stealthz$', views.stealth, name='stealth'),
    re_path(r'^api/search/', include('search.urls'), name='search'),
    re_path(r'^api/probers/get_prober_channel', views.get_prober_channel, name='get_prober_channel'),
    re_path(r'^api/sync/$', sync, name="sync"),
]

# if activated, turn on django prometheus urls
if "django_prometheus" in settings.INSTALLED_APPS:
    urlpatterns += [
        re_path('', include('django_prometheus.urls')),
    ]


# Add public api endpoints
urlpatterns += [
    re_path(r'^api/public/channel/(?P<channel_id>[^/]+)', public_views.get_channel_name_by_id, name='get_channel_name_by_id'),
    re_path(r'^api/public/(?P<version>[^/]+)/channels$', public_views.get_public_channel_list, name='get_public_channel_list'),
    re_path(r'^api/public/(?P<version>[^/]+)/channels/lookup/(?P<identifier>[^/]+)', public_views.get_public_channel_lookup, name='get_public_channel_lookup'),
    re_path(r'^api/public/info', public_views.InfoViewSet.as_view({'get': 'list'}), name='info'),
]

# Add node api enpoints
urlpatterns += [
    re_path(r'^api/get_channel_details/(?P<channel_id>[^/]*)$', node_views.get_channel_details, name='get_channel_details'),
    re_path(r'^api/get_node_details/(?P<node_id>[^/]*)$', node_views.get_node_details, name='get_node_details'),
    re_path(r'^api/get_node_diff/(?P<updated_id>[^/]*)/(?P<original_id>[^/]*)$', node_views.get_node_diff, name='get_node_diff'),
    re_path(r'^api/generate_node_diff/(?P<updated_id>[^/]*)/(?P<original_id>[^/]*)$', node_views.generate_node_diff, name='generate_node_diff'),
]

# Add file api enpoints
urlpatterns += [
    re_path(r'^zipcontent/(?P<zipped_filename>[^/]+)/(?P<embedded_filepath>.*)', zip_views.ZipContentView.as_view(), {}, "zipcontent"),
]

# Add settings endpoints
urlpatterns += [
    re_path(r'^api/delete_user_account/$', settings_views.DeleteAccountView.as_view(), name='delete_user_account'),
    re_path(r'^api/export_user_data/$', settings_views.export_user_data, name='export_user_data'),
    re_path(r'^api/change_password/$', settings_views.UserPasswordChangeView.as_view(), name='change_password'),
    re_path(r'^api/update_user_full_name/$', settings_views.UsernameChangeView.as_view(), name='update_user_full_name'),
    re_path(r'^settings/issues', settings_views.IssuesSettingsView.as_view(), name='issues_settings'),
    re_path(r'^settings/request_storage', settings_views.StorageSettingsView.as_view(), name='request_storage'),
    re_path(r'^policies/update', settings_views.PolicyAcceptView.as_view(), name='policy_update'),
]

# Add internal endpoints
urlpatterns += [
    re_path(r'^api/internal/authenticate_user_internal$', internal_views.authenticate_user_internal, name="authenticate_user_internal"),
    re_path(r'^api/internal/check_version$', internal_views.check_version, name="check_version"),
    re_path(r'^api/internal/file_diff$', internal_views.file_diff, name="file_diff"),
    re_path(r'^api/internal/file_upload$', internal_views.api_file_upload, name="api_file_upload"),
    re_path(r'^api/internal/publish_channel$', internal_views.api_publish_channel, name="api_publish_channel"),
    re_path(r'^api/internal/activate_channel_internal$', internal_views.activate_channel_internal, name='activate_channel_internal'),
    re_path(r'^api/internal/check_user_is_editor$', internal_views.check_user_is_editor, name='check_user_is_editor'),
    re_path(r'^api/internal/get_tree_data$', internal_views.get_tree_data, name='get_tree_data'),
    re_path(r'^api/internal/get_node_tree_data$', internal_views.get_node_tree_data, name='get_node_tree_data'),
    re_path(r'^api/internal/create_channel$', internal_views.api_create_channel_endpoint, name="api_create_channel"),
    re_path(r'^api/internal/add_nodes$', internal_views.api_add_nodes_to_tree, name="api_add_nodes_to_tree"),
    re_path(r'^api/internal/finish_channel$', internal_views.api_commit_channel, name="api_finish_channel"),
    re_path(r'^api/internal/get_channel_status_bulk$', internal_views.get_channel_status_bulk, name="get_channel_status_bulk"),
]

# Add admin endpoints
urlpatterns += [
    re_path(r'^api/send_custom_email/$', admin_views.send_custom_email, name='send_custom_email'),
]

urlpatterns += [re_path(r'^jsreverse/$', django_js_reverse_views.urls_js, name='js_reverse')]

# I18N Endpoints
js_info_dict = {
    'packages': ('your.app.package',),
}

urlpatterns += [
    re_path(r'^i18n/', include('django.conf.urls.i18n')),
]

# Include all URLS prefixed by language
urlpatterns += i18n_patterns(
    re_path(r'^$', views.base, name='base'),
    re_path(r"^i18n/setlang/$", views.set_language, name="set_language"),
    re_path(r'^channels/$', views.channel_list, name='channels'),
    # Redirect deprecated staging URL to new URL
    re_path(r'^channels/(?P<channel_id>[^/]{32})/staging/$', StagingPageRedirectView.as_view(), name='staging_redirect'),
    re_path(r'^channels/(?P<channel_id>[^/]{32})/$', views.channel, name='channel'),
    re_path(r'^accounts/login/$', registration_views.login, name='login'),
    re_path(r'^accounts/logout/$', registration_views.logout, name='logout'),
    re_path(r'^accounts/request_activation_link/$', registration_views.request_activation_link, name='request_activation_link'),
    re_path(r"^accounts/$", views.accounts, name="accounts"),
    re_path(r'^accounts/password/reset/$', registration_views.UserPasswordResetView.as_view(), name='auth_password_reset'),
    re_path(r'^accounts/password/reset/confirm/(?P<uidb64>[0-9A-Za-z_\-]+)/(?P<token>[0-9A-Za-z]{1,13}-[0-9A-Za-z]{1,20})/$',
            registration_views.UserPasswordResetConfirmView.as_view(), name='auth_password_reset_confirm'),
    re_path(r'^accounts/register/$', registration_views.UserRegistrationView.as_view(), name='register'),
    re_path(r'^activate/(?P<activation_key>[-:\w]+)/$', registration_views.UserActivationView.as_view(), name='registration_activate'),
    re_path(r'^api/send_invitation_email/$', registration_views.send_invitation_email, name='send_invitation_email'),
    re_path(r'^new/accept_invitation/(?P<email>[^/]+)/', registration_views.new_user_redirect, name="accept_invitation_and_registration"),
    re_path(r'^api/deferred_user_data/$', registration_views.deferred_user_data, name="deferred_user_data"),
    re_path(r'^settings/$', settings_views.settings, name='settings'),
    re_path(r'^administration/', admin_views.administration, name='administration'),
    re_path(r'^manifest.webmanifest$', pwa.ManifestView.as_view(), name="manifest"),
)
