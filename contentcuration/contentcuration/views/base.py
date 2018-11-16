import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.sites.shortcuts import get_current_site
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import PermissionDenied
from django.core.urlresolvers import reverse_lazy
from django.db.models import Case
from django.db.models import IntegerField
from django.db.models import Q
from django.db.models import Value
from django.db.models import When
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.http import HttpResponseForbidden
from django.http import HttpResponseNotFound
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.cache import cache_page
from django.views.decorators.csrf import csrf_exempt
from le_utils.constants import exercises
from le_utils.constants import roles
from rest_framework.authentication import BasicAuthentication
from rest_framework.authentication import SessionAuthentication
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import api_view
from rest_framework.decorators import authentication_classes
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from contentcuration.api import activate_channel
from contentcuration.api import add_editor_to_channel
from contentcuration.api import get_staged_diff
from contentcuration.decorators import browser_is_supported
from contentcuration.decorators import can_access_channel
from contentcuration.decorators import can_edit_channel
from contentcuration.decorators import has_accepted_policies
from contentcuration.models import Channel
from contentcuration.models import ContentKind
from contentcuration.models import ContentNode
from contentcuration.models import FileFormat
from contentcuration.models import FormatPreset
from contentcuration.models import Invitation
from contentcuration.models import Language
from contentcuration.models import License
from contentcuration.models import User
from contentcuration.models import VIEW_ACCESS
from contentcuration.serializers import AltChannelListSerializer
from contentcuration.serializers import ChannelListSerializer
from contentcuration.serializers import ChannelSerializer
from contentcuration.serializers import ContentKindSerializer
from contentcuration.serializers import CurrentUserSerializer
from contentcuration.serializers import FileFormatSerializer
from contentcuration.serializers import FormatPresetSerializer
from contentcuration.serializers import InvitationSerializer
from contentcuration.serializers import LanguageSerializer
from contentcuration.serializers import LicenseSerializer
from contentcuration.serializers import RootNodeSerializer
from contentcuration.serializers import UserChannelListSerializer
from contentcuration.tasks import exportchannel_task
from contentcuration.tasks import generatechannelcsv_task
from contentcuration.utils.channelcache import ChannelCacher
from contentcuration.utils.messages import get_messages

PUBLIC_CHANNELS_CACHE_DURATION = 30  # seconds


@browser_is_supported
def base(request):
    if request.user.is_authenticated():
        return redirect('channels')
    else:
        return redirect('accounts/login')


def health(request):
    c = Channel.objects.first()
    if c:
        return HttpResponse(c.name)
    else:
        return HttpResponse("No channels created yet!")


def stealth(request):
    return HttpResponse("<3")


def get_or_set_cached_constants(constant, serializer):
    cached_data = cache.get(constant.__name__)
    if cached_data:
        return cached_data
    constant_objects = constant.objects.all()
    constant_serializer = serializer(constant_objects, many=True)
    constant_data = JSONRenderer().render(constant_serializer.data)
    cache.set(constant.__name__, constant_data, None)
    return constant_data


@has_accepted_policies
def redirect_to_channel(request, channel_id):
    channel = Channel.objects.get(pk=channel_id)
    if channel.editors.filter(pk=request.user.pk).exists():
        return redirect(reverse_lazy('channel', kwargs={'channel_id': channel_id}))

    # it will check the view authorization after the redirect
    return redirect(reverse_lazy('channel_view_only', kwargs={'channel_id': channel_id}))


def redirect_to_channel_edit(request, channel_id):
    return redirect(reverse_lazy('channel', kwargs={'channel_id': channel_id}))


def redirect_to_channel_view(request, channel_id):
    return redirect(reverse_lazy('channel_view_only', kwargs={'channel_id': channel_id}))


def channel_page(request, channel, allow_edit=False, staging=False):
    channel_serializer = ChannelSerializer(channel)
    channel_list = Channel.objects.select_related('main_tree').prefetch_related('editors').prefetch_related('viewers')\
                          .exclude(id=channel.pk).filter(Q(deleted=False) & (Q(editors=request.user) | Q(viewers=request.user)))\
                          .annotate(is_view_only=Case(When(editors=request.user, then=Value(0)), default=Value(1), output_field=IntegerField()))\
                          .distinct().values("id", "name", "is_view_only").order_by('name')

    token = None
    if channel.secret_tokens.filter(is_primary=True).exists():
        token = channel.secret_tokens.filter(is_primary=True).first().token
        token = token[:5] + "-" + token[5:]

    json_renderer = JSONRenderer()
    return render(request, 'channel_edit.html', {"allow_edit": allow_edit,
                                                 "staging": staging,
                                                 "is_public": channel.public,
                                                 "channel": json_renderer.render(channel_serializer.data),
                                                 "channel_id": channel.pk,
                                                 "channel_name": channel.name,
                                                 "channel_list": channel_list,
                                                 "current_user": json_renderer.render(CurrentUserSerializer(request.user).data),
                                                 "preferences": json.dumps(channel.content_defaults),
                                                 "messages": get_messages(),
                                                 "primary_token": token or channel.pk,
                                                 "title": settings.DEFAULT_TITLE,
                                                 })


@login_required
@browser_is_supported
@has_accepted_policies
@authentication_classes((SessionAuthentication, BasicAuthentication, TokenAuthentication))
@permission_classes((IsAuthenticated,))
def channel_list(request):
    languages = get_or_set_cached_constants(Language, LanguageSerializer)
    fileformats = get_or_set_cached_constants(FileFormat, FileFormatSerializer)
    licenses = get_or_set_cached_constants(License, LicenseSerializer)
    formatpresets = get_or_set_cached_constants(FormatPreset, FormatPresetSerializer)
    contentkinds = get_or_set_cached_constants(ContentKind, ContentKindSerializer)
    languages = get_or_set_cached_constants(Language, LanguageSerializer)

    return render(request, 'channel_list.html', {"channel_name": False,
                                                 "current_user": JSONRenderer().render(UserChannelListSerializer(request.user).data),
                                                 "user_preferences": json.dumps(request.user.content_defaults),
                                                 "langs_list": languages,
                                                 "fileformat_list": fileformats,
                                                 "license_list": licenses,
                                                 "fpreset_list": formatpresets,
                                                 "ckinds_list": contentkinds,
                                                 "langs_list": languages,
                                                 "messages": get_messages(),
                                                 })


@api_view(['GET'])
@authentication_classes((SessionAuthentication, BasicAuthentication, TokenAuthentication))
@permission_classes((IsAuthenticated,))
def get_user_channels(request):
    channel_list = Channel.objects.prefetch_related('editors', 'viewers')\
        .filter(Q(deleted=False) & (Q(editors=request.user.pk) | Q(viewers=request.user.pk)))\
        .annotate(is_view_only=Case(When(editors=request.user, then=Value(0)), default=Value(1), output_field=IntegerField()))
    channel_serializer = ChannelListSerializer(channel_list, many=True)

    return Response(channel_serializer.data)


@api_view(['GET'])
@authentication_classes((SessionAuthentication, BasicAuthentication, TokenAuthentication))
@permission_classes((IsAuthenticated,))
def get_user_bookmarked_channels(request):
    bookmarked_channels = request.user.bookmarked_channels.exclude(deleted=True)\
        .select_related('main_tree').prefetch_related('editors')\
        .defer('trash_tree', 'clipboard_tree', 'staging_tree', 'chef_tree', 'previous_tree', 'viewers')
    channel_serializer = AltChannelListSerializer(bookmarked_channels, many=True)
    return Response(channel_serializer.data)


@api_view(['GET'])
@authentication_classes((SessionAuthentication, BasicAuthentication, TokenAuthentication))
@permission_classes((IsAuthenticated,))
def get_user_edit_channels(request):
    edit_channels = request.user.editable_channels.exclude(deleted=True)\
        .select_related('main_tree').prefetch_related('editors')\
        .defer('trash_tree', 'clipboard_tree', 'staging_tree', 'chef_tree', 'previous_tree', 'viewers')
    channel_serializer = AltChannelListSerializer(edit_channels, many=True)
    return Response(channel_serializer.data)


@cache_page(PUBLIC_CHANNELS_CACHE_DURATION)
@api_view(['GET'])
@authentication_classes((SessionAuthentication, BasicAuthentication, TokenAuthentication))
@permission_classes((IsAuthenticated,))
def get_user_public_channels(request):
    channels = ChannelCacher.get_public_channels(defer_nonmain_trees=True)
    channel_serializer = AltChannelListSerializer(channels, many=True)
    return Response(channel_serializer.data)


@api_view(['GET'])
@authentication_classes((SessionAuthentication, BasicAuthentication, TokenAuthentication))
@permission_classes((IsAuthenticated,))
def get_user_view_channels(request):
    view_channels = request.user.view_only_channels.exclude(deleted=True)\
        .select_related('main_tree').prefetch_related('editors')\
        .defer('trash_tree', 'clipboard_tree', 'staging_tree', 'chef_tree', 'previous_tree', 'viewers')

    channel_serializer = AltChannelListSerializer(view_channels, many=True)
    return Response(channel_serializer.data)


@api_view(['GET'])
@authentication_classes((SessionAuthentication, BasicAuthentication, TokenAuthentication))
@permission_classes((IsAuthenticated,))
def get_user_pending_channels(request):
    pending_list = Invitation.objects.select_related('channel', 'sender')\
        .filter(invited=request.user, channel__deleted=False)\
        .exclude(channel=None)  # Don't include channels that have been deleted
    invitation_serializer = InvitationSerializer(pending_list, many=True)

    return Response(invitation_serializer.data)


@login_required
@browser_is_supported
@has_accepted_policies
@authentication_classes((SessionAuthentication, BasicAuthentication, TokenAuthentication))
@permission_classes((IsAuthenticated,))
def channel(request, channel_id):
    channel = get_object_or_404(Channel, id=channel_id, deleted=False)

    # Check user has permission to view channel
    if not channel.editors.filter(id=request.user.id).exists() and not request.user.is_admin:
        return redirect(reverse_lazy('channel_view_only', kwargs={'channel_id': channel_id}))

    return channel_page(request, channel, allow_edit=True)


@login_required
@browser_is_supported
@can_access_channel
@has_accepted_policies
@authentication_classes((SessionAuthentication, BasicAuthentication, TokenAuthentication))
@permission_classes((IsAuthenticated,))
def channel_view_only(request, channel_id):
    channel = get_object_or_404(Channel, id=channel_id, deleted=False)
    return channel_page(request, channel)


@login_required
@browser_is_supported
@can_edit_channel
@has_accepted_policies
@authentication_classes((SessionAuthentication, BasicAuthentication, TokenAuthentication))
@permission_classes((IsAuthenticated,))
def channel_staging(request, channel_id):
    channel = Channel.objects.get(pk=channel_id)

    if not channel.staging_tree:
        return render(request, 'staging_not_found.html')

    return channel_page(request, channel, allow_edit=True, staging=True)


@csrf_exempt
@authentication_classes((SessionAuthentication, BasicAuthentication, TokenAuthentication))
@permission_classes((IsAuthenticated,))
def publish_channel(request):
    logging.debug("Entering the publish_channel endpoint")
    if request.method != 'POST':
        return HttpResponseBadRequest("Only POST requests are allowed on this endpoint.")

    data = json.loads(request.body)

    try:
        channel_id = data["channel_id"]
        request.user.can_edit(channel_id)
    except KeyError:
        raise ObjectDoesNotExist("Missing attribute from data: {}".format(data))

    exportchannel_task.delay(channel_id, user_id=request.user.pk)
    return HttpResponse(json.dumps({
        "success": True,
        "channel": channel_id
    }))


@api_view(['GET'])
@authentication_classes((TokenAuthentication, SessionAuthentication))
@permission_classes((IsAuthenticated,))
def accessible_channels(request, channel_id):
    # Used for import modal
    accessible_list = ContentNode.objects.filter(
        pk__in=Channel.objects.select_related('main_tree')
        .filter(Q(deleted=False) & (Q(public=True) | Q(editors=request.user) | Q(viewers=request.user)))
        .exclude(pk=channel_id).values_list('main_tree_id', flat=True)
    )

    serializer = RootNodeSerializer(accessible_list, many=True)
    return Response(serializer.data)


def accept_channel_invite(request):
    if request.method != 'POST':
        return HttpResponseBadRequest("Only POST requests are allowed on this endpoint.")

    data = json.loads(request.body)
    invitation = Invitation.objects.get(pk=data['invitation_id'])
    channel = invitation.channel
    channel.is_view_only = invitation.share_mode == VIEW_ACCESS
    channel_serializer = AltChannelListSerializer(channel)
    add_editor_to_channel(invitation)

    return HttpResponse(JSONRenderer().render(channel_serializer.data))


def activate_channel_endpoint(request):
    if request.method != 'POST':
        return HttpResponseBadRequest("Only POST requests are allowed on this endpoint.")

    data = json.loads(request.body)
    channel = Channel.objects.get(pk=data['channel_id'])
    try:
        activate_channel(channel, request.user)
    except PermissionDenied as e:
        return HttpResponseForbidden(str(e))

    return HttpResponse(json.dumps({"success": True}))


def get_staged_diff_endpoint(request):
    if request.method == 'POST':
        return HttpResponse(json.dumps(get_staged_diff(json.loads(request.body)['channel_id'])))

    return HttpResponseBadRequest("Only POST requests are allowed on this endpoint.")


@authentication_classes((SessionAuthentication, BasicAuthentication, TokenAuthentication))
@permission_classes((IsAuthenticated,))
def add_bookmark(request):
    if request.method != 'POST':
        return HttpResponseBadRequest("Only POST requests are allowed on this endpoint.")

    data = json.loads(request.body)

    try:
        user = User.objects.get(pk=data["user_id"])
        channel = Channel.objects.get(pk=data["channel_id"])
        channel.bookmarked_by.add(user)
        channel.save()

        return HttpResponse(json.dumps({"success": True}))
    except ObjectDoesNotExist:
        return HttpResponseNotFound('Channel with id {} not found'.format(data["channel_id"]))


@authentication_classes((SessionAuthentication, BasicAuthentication, TokenAuthentication))
@permission_classes((IsAuthenticated,))
def remove_bookmark(request):
    if request.method != 'POST':
        return HttpResponseBadRequest("Only POST requests are allowed on this endpoint.")

    data = json.loads(request.body)

    try:
        user = User.objects.get(pk=data["user_id"])
        channel = Channel.objects.get(pk=data["channel_id"])
        channel.bookmarked_by.remove(user)
        channel.save()

        return HttpResponse(json.dumps({"success": True}))
    except ObjectDoesNotExist:
        return HttpResponseNotFound('Channel with id {} not found'.format(data["channel_id"]))


@authentication_classes((SessionAuthentication, BasicAuthentication, TokenAuthentication))
@permission_classes((IsAuthenticated,))
def set_channel_priority(request):
    if request.method != 'POST':
        return HttpResponseBadRequest("Only POST requests are allowed on this endpoint.")

    data = json.loads(request.body)

    try:
        channel = Channel.objects.get(pk=data["channel_id"])
        channel.priority = data["priority"]
        channel.save()

        return HttpResponse(json.dumps({"success": True}))
    except ObjectDoesNotExist:
        return HttpResponseNotFound('Channel with id {} not found'.format(data["channel_id"]))


@authentication_classes((SessionAuthentication, BasicAuthentication, TokenAuthentication))
@permission_classes((IsAuthenticated,))
def download_channel_content_csv(request, channel_id):
    """ Writes list of channels to csv, which is then emailed """
    site = get_current_site(request)
    generatechannelcsv_task.delay(channel_id, site.domain, request.user.id)

    return HttpResponse({"success": True})


@authentication_classes((SessionAuthentication, BasicAuthentication, TokenAuthentication))
@permission_classes((IsAuthenticated,))
def test_progressbar(request):
    time.sleep(0.5)
    return HttpResponse(json.dumps({"success": True}))
