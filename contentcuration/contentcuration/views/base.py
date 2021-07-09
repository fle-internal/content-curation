import json
from builtins import str
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.db.models import IntegerField
from django.db.models import OuterRef
from django.db.models import Subquery
from django.http import HttpResponse
from django.http import HttpResponseForbidden
from django.http import HttpResponseNotFound
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import is_valid_path
from django.urls import reverse
from django.urls import reverse_lazy
from django.urls import translate_url
from django.utils.translation import get_language
from django.utils.translation import LANGUAGE_SESSION_KEY
from django.views.decorators.http import require_POST
from django.views.i18n import LANGUAGE_QUERY_PARAMETER
from rest_framework.authentication import BasicAuthentication
from rest_framework.authentication import SessionAuthentication
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import api_view
from rest_framework.decorators import authentication_classes
from rest_framework.decorators import permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .json_dump import json_for_parse_from_data
from .json_dump import json_for_parse_from_serializer
from contentcuration.api import activate_channel
from contentcuration.decorators import browser_is_supported
from contentcuration.models import Channel
from contentcuration.models import ChannelSet
from contentcuration.models import ContentKind
from contentcuration.models import DEFAULT_USER_PREFERENCES
from contentcuration.models import Language
from contentcuration.models import License
from contentcuration.serializers import SimplifiedChannelProbeCheckSerializer
from contentcuration.utils.i18n import SUPPORTED_LANGUAGES
from contentcuration.utils.messages import get_messages
from contentcuration.viewsets.channelset import PublicChannelSetSerializer

PUBLIC_CHANNELS_CACHE_DURATION = 30  # seconds

MESSAGES = "i18n_messages"
PREFERENCES = "user_preferences"
CURRENT_USER = "current_user"
CHANNEL_EDIT_GLOBAL = "CHANNEL_EDIT_GLOBAL"

user_fields = (
    "email",
    "first_name",
    "last_name",
    "id",
    "is_active",
    "is_admin",
    "disk_space",
    "disk_space_used",
    "clipboard_tree_id",
    "policies",
    "feature_flags",
)


def current_user_for_context(user):
    if not user or user.is_anonymous:
        return json_for_parse_from_data(None)

    return json_for_parse_from_data({field: getattr(user, field) for field in user_fields})


@browser_is_supported
@permission_classes((AllowAny,))
def base(request):
    if settings.LIBRARY_MODE:
        return channel_list(request)
    if request.user.is_authenticated:
        return redirect(reverse_lazy("channels"))
    return redirect(reverse_lazy("accounts"))


""" HEALTH CHECKS """


def health(request):
    c = Channel.objects.first()
    if c:
        return HttpResponse(c.name)
    return HttpResponse("No channels created yet!")


def stealth(request):
    return HttpResponse("<3")


@api_view(["GET"])
@authentication_classes((TokenAuthentication, SessionAuthentication))
@permission_classes((IsAuthenticated,))
def get_prober_channel(request):
    if not request.user.is_admin:
        return HttpResponseForbidden()

    channel = Channel.objects.filter(editors=request.user).first()
    if not channel:
        channel = Channel.objects.create(name="Prober channel", editors=[request.user])

    return Response(SimplifiedChannelProbeCheckSerializer(channel).data)


""" END HEALTH CHECKS """


@browser_is_supported
@permission_classes((AllowAny,))
def channel_list(request):
    anon = settings.LIBRARY_MODE or request.user.is_anonymous
    current_user = current_user_for_context(None if anon else request.user)
    preferences = DEFAULT_USER_PREFERENCES if anon else request.user.content_defaults

    public_channel_list = Channel.objects.filter(
        public=True, main_tree__published=True, deleted=False,
    ).values_list("main_tree__tree_id", flat=True)

    # Get public channel languages
    public_lang_query = (
        Language.objects.filter(
            channel_language__public=True,
            channel_language__main_tree__published=True,
            channel_language__deleted=False,
        )
        .values("lang_code")
        .annotate(count=Count("lang_code"))
        .order_by("lang_code")
    )
    languages = {lang["lang_code"]: lang["count"] for lang in public_lang_query}

    # Get public channel licenses
    public_license_query = (
        License.objects.filter(contentnode__tree_id__in=public_channel_list)
        .values_list("id", flat=True)
        .order_by("id")
        .distinct()
    )
    licenses = list(public_license_query)

    # Get public channel kinds
    public_kind_query = (
        ContentKind.objects.filter(contentnodes__tree_id__in=public_channel_list)
        .values_list("kind", flat=True)
        .order_by("kind")
        .distinct()
    )
    kinds = list(public_kind_query)

    # Get public channel sets
    public_channelset_query = ChannelSet.objects.filter(public=True).annotate(
        count=SQCountDistinct(
            Channel.objects.filter(
                secret_tokens=OuterRef("secret_token"),
                public=True,
                main_tree__published=True,
                deleted=False,
            ).values_list("id", flat=True),
            field="id",
        )
    )
    return render(
        request,
        "channel_list.html",
        {
            CURRENT_USER: current_user,
            PREFERENCES: json_for_parse_from_data(preferences),
            MESSAGES: json_for_parse_from_data(get_messages()),
            "LIBRARY_MODE": settings.LIBRARY_MODE,
            "public_languages": json_for_parse_from_data(languages),
            "public_kinds": json_for_parse_from_data(kinds),
            "public_licenses": json_for_parse_from_data(licenses),
            "public_collections": json_for_parse_from_serializer(
                PublicChannelSetSerializer(public_channelset_query, many=True)
            ),
        },
    )


@browser_is_supported
@permission_classes((AllowAny,))
def accounts(request):
    if not request.user.is_anonymous:
        return redirect("channels")
    return render(
        request,
        "accounts.html",
        {
            PREFERENCES: json_for_parse_from_data(DEFAULT_USER_PREFERENCES),
            MESSAGES: json_for_parse_from_data(get_messages()),
        },
    )


@login_required
@browser_is_supported
@authentication_classes(
    (SessionAuthentication, BasicAuthentication, TokenAuthentication)
)
@permission_classes((IsAuthenticated,))
def channel(request, channel_id):
    channel_error = ""

    # Check if channel exists
    try:
        channel = Channel.filter_view_queryset(Channel.objects.all(), request.user).get(id=channel_id)
    except Channel.DoesNotExist:
        channel_error = "CHANNEL_EDIT_ERROR_CHANNEL_NOT_FOUND"
        channel = None

    if channel is not None:
        # If user can view channel, but it's deleted, then we show
        # an option to restore the channel in the Administration page
        if channel.deleted:
            channel_error = 'CHANNEL_EDIT_ERROR_CHANNEL_DELETED'

    return render(
        request,
        "channel_edit.html",
        {
            CHANNEL_EDIT_GLOBAL: json_for_parse_from_data(
                {"channel_id": channel_id, "channel_error": channel_error}
            ),
            CURRENT_USER: current_user_for_context(request.user),
            PREFERENCES: json_for_parse_from_data(request.user.content_defaults),
            MESSAGES: json_for_parse_from_data(get_messages()),
        },
    )


class SQCountDistinct(Subquery):
    # Include ALIAS at the end to support Postgres
    template = (
        "(SELECT COUNT(DISTINCT %(field)s) FROM (%(subquery)s) AS %(field)s__sum)"
    )
    output_field = IntegerField()


@api_view(['POST'])
@authentication_classes((SessionAuthentication,))
@permission_classes((IsAuthenticated,))
def activate_channel_endpoint(request):
    data = request.data
    try:
        channel = Channel.filter_edit_queryset(Channel.objects.all(), request.user).get(pk=data["channel_id"])
    except Channel.DoesNotExist:
        return HttpResponseNotFound("Channel not found")
    changes = []
    try:
        change = activate_channel(channel, request.user)
        changes.append(change)
    except PermissionDenied as e:
        return HttpResponseForbidden(str(e))

    return HttpResponse(json.dumps({"success": True, "changes": changes}))


# Taken from kolibri.core.views which was
# modified from django.views.i18n
@require_POST
def set_language(request):
    """
    Since this view changes how the user will see the rest of the site, it must
    only be accessed as a POST request. If called as a GET request, it will
    error.
    """
    payload = json.loads(request.body)
    lang_code = payload.get(LANGUAGE_QUERY_PARAMETER)
    next_url = urlsplit(payload.get("next")) if payload.get("next") else None
    if lang_code and lang_code in SUPPORTED_LANGUAGES:
        if next_url and is_valid_path(next_url.path):
            # If it is a recognized path, then translate it to the new language and return it.
            next_path = urlunsplit(
                (
                    next_url[0],
                    next_url[1],
                    translate_url(next_url[2], lang_code),
                    next_url[3],
                    next_url[4],
                )
            )
        else:
            # Just redirect to the base URL w/ the lang_code
            next_path = translate_url(reverse('base'), lang_code)
        response = HttpResponse(next_path)
        if hasattr(request, "session"):
            request.session[LANGUAGE_SESSION_KEY] = lang_code
    else:
        lang_code = get_language()
        if next_url and is_valid_path(next_url.path):
            # If it is a recognized path, then translate it using the default language code for this device
            next_path = urlunsplit(
                (
                    next_url[0],
                    next_url[1],
                    translate_url(next_url[2], lang_code),
                    next_url[3],
                    next_url[4],
                )
            )
        else:
            # Just redirect to the base URL w/ the lang_code, likely the default language
            next_path = translate_url(reverse('base'), lang_code)
        response = HttpResponse(next_path)
        if hasattr(request, "session"):
            request.session.pop(LANGUAGE_SESSION_KEY, "")
    return response
