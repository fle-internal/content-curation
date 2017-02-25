import copy
import json
import logging
import os
import re
import hashlib
import shutil
import tempfile
import random
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, get_object_or_404, redirect, render_to_response
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core import paginator, serializers
from django.core.management import call_command
from django.core.exceptions import ObjectDoesNotExist
from django.core.context_processors import csrf
from django.db import transaction
from django.db.models import Q, Case, When, Value, IntegerField
from django.core.urlresolvers import reverse_lazy
from django.core.files import File as DjFile
from rest_framework.renderers import JSONRenderer
from contentcuration.api import write_file_to_storage, check_supported_browsers
from contentcuration.models import Exercise, AssessmentItem, Channel, License, FileFormat, File, FormatPreset, ContentKind, ContentNode, ContentTag, User, Invitation, generate_file_on_disk_name, generate_storage_url
from contentcuration.serializers import AssessmentItemSerializer, ChannelListSerializer, ChannelSerializer, LicenseSerializer, FileFormatSerializer, FormatPresetSerializer, ContentKindSerializer, ContentNodeSerializer, TagSerializer, UserSerializer, CurrentUserSerializer
from django.core.cache import cache
from le_utils.constants import format_presets, content_kinds, file_formats
from rest_framework.authentication import SessionAuthentication, BasicAuthentication, TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from pressurecooker.videos import guess_video_preset_by_resolution, extract_thumbnail_from_video, compress_video
from pressurecooker.images import create_tiled_image
from django.core.cache import cache

def base(request):
    if not check_supported_browsers(request.META['HTTP_USER_AGENT']):
        return redirect(reverse_lazy('unsupported_browser'))
    if request.user.is_authenticated():
        return redirect('channels')
    else:
        return redirect('accounts/login')

def testpage(request):
    return render(request, 'test.html')

def unsupported_browser(request):
    return render(request, 'unsupported_browser.html')

def unauthorized(request):
    return render(request, 'unauthorized.html')

def channel_page(request, channel, allow_edit=False):
    channel_serializer =  ChannelSerializer(channel)
    accessible_channel_list = Channel.objects.filter(deleted=False).filter( Q(public=True) | Q(editors=request.user) | Q(viewers=request.user))
    accessible_channel_list = ChannelSerializer.setup_eager_loading(accessible_channel_list)
    accessible_channel_list_serializer = ChannelSerializer(accessible_channel_list, many=True)

    channel_list = accessible_channel_list.filter(Q(editors=request.user) | Q(viewers=request.user))\
                    .distinct()\
                    .exclude(id=channel.pk)\
                    .annotate(is_view_only=Case(When(editors=request.user, then=Value(0)),default=Value(1),output_field=IntegerField()))\
                    .values("id", "name", "is_view_only")
    fileformats = get_or_set_cached_constants(FileFormat, FileFormatSerializer)
    licenses = get_or_set_cached_constants(License, LicenseSerializer)
    formatpresets = get_or_set_cached_constants(FormatPreset, FormatPresetSerializer)
    contentkinds = get_or_set_cached_constants(ContentKind, ContentKindSerializer)

    channel_tags = ContentTag.objects.filter(channel = channel)
    channel_tags_serializer = TagSerializer(channel_tags, many=True)

    json_renderer = JSONRenderer()

    return render(request, 'channel_edit.html', {"allow_edit":allow_edit,
                                                "channel" : json_renderer.render(channel_serializer.data),
                                                "channel_id" : channel.pk,
                                                "channel_name": channel.name,
                                                "accessible_channels" : json_renderer.render(accessible_channel_list_serializer.data),
                                                "channel_list" : channel_list,
                                                "fileformat_list" : fileformats,
                                                 "license_list" : licenses,
                                                 "fpreset_list" : formatpresets,
                                                 "ckinds_list" : contentkinds,
                                                 "ctags": json_renderer.render(channel_tags_serializer.data),
                                                 "current_user" : json_renderer.render(CurrentUserSerializer(request.user).data)})

@login_required
@authentication_classes((SessionAuthentication, BasicAuthentication, TokenAuthentication))
@permission_classes((IsAuthenticated,))
def channel_list(request):
    if not check_supported_browsers(request.META['HTTP_USER_AGENT']):
        return redirect(reverse_lazy('unsupported_browser'))

    channel_list = Channel.objects.select_related('main_tree').filter(Q(deleted=False) & (Q(editors=request.user.pk) | Q(viewers=request.user.pk)))\
                    .annotate(is_view_only=Case(When(editors=request.user, then=Value(0)),default=Value(1),output_field=IntegerField()))

    channel_serializer = ChannelListSerializer(channel_list, many=True)

    licenses = get_or_set_cached_constants(License, LicenseSerializer)
    return render(request, 'channel_list.html', {"channels" : JSONRenderer().render(channel_serializer.data),
                                                 "channel_name" : False,
                                                 "license_list" : licenses,
                                                 "current_user" : JSONRenderer().render(UserSerializer(request.user).data)})

@login_required
@authentication_classes((SessionAuthentication, BasicAuthentication, TokenAuthentication))
@permission_classes((IsAuthenticated,))
def channel(request, channel_id):
    # Check if browser is supported
    if not check_supported_browsers(request.META['HTTP_USER_AGENT']):
        return redirect(reverse_lazy('unsupported_browser'))

    channel = get_object_or_404(Channel, id=channel_id, deleted=False)

    # Check user has permission to view channel
    if request.user not in channel.editors.all() and not request.user.is_admin:
        return redirect(reverse_lazy('unauthorized'))

    return channel_page(request, channel, allow_edit=True)

@login_required
@authentication_classes((SessionAuthentication, BasicAuthentication, TokenAuthentication))
@permission_classes((IsAuthenticated,))
def channel_view_only(request, channel_id):
    # Check if browser is supported
    if not check_supported_browsers(request.META['HTTP_USER_AGENT']):
        return redirect(reverse_lazy('unsupported_browser'))

    channel = get_object_or_404(Channel, id=channel_id, deleted=False)

    # Check user has permission to view channel
    if request.user not in channel.editors.all() and request.user not in channel.viewers.all() and not request.user.is_admin:
        return redirect(reverse_lazy('unauthorized'))

    return channel_page(request, channel)

def get_or_set_cached_constants(constant, serializer):
    cached_data = cache.get(constant.__name__)
    if cached_data:
        return cached_data
    constant_objects = constant.objects.all()
    constant_serializer = serializer(constant_objects, many=True)
    constant_data = JSONRenderer().render(constant_serializer.data)
    cache.set(constant.__name__, constant_data, None)
    return constant_data

def exercise_list(request):

    exercise_list = Exercise.objects.all().order_by('title')

    paged_list = paginator.Paginator(exercise_list, 25)  # Show 25 exercises per page

    page = request.GET.get('page')

    try:
        exercises = paged_list.page(page)
    except paginator.PageNotAnInteger:
        # If page is not an integer, deliver first page.
        exercises = paged_list.page(1)
    except paginator.EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        exercises = paged_list.page(paginator.num_pages)

    # serializer = ExerciseSerializer(exercises.object_list, many=True)

    return render(request, 'exercise_list.html', {"exercises": exercises, "blob": JSONRenderer().render(serializer.data)})


def exercise(request, exercise_id):

    exercise = get_object_or_404(ContentNode, id=exercise_id)

    serializer = ContentNodeSerializer(exercise)

    assessment_items = AssessmentItem.objects.filter(exercise=exercise)

    assessment_serialize = AssessmentItemSerializer(assessment_items, many=True)

    return render(request, 'exercise_edit.html', {"exercise": JSONRenderer().render(serializer.data), "assessment_items": JSONRenderer().render(assessment_serialize.data)})

# TODO-BLOCKER: remove this csrf_exempt! People might upload random stuff here and we don't want that.
@csrf_exempt
def file_upload(request):
    if request.method == 'POST':
        preset = FormatPreset.objects.get(id=request.META.get('HTTP_PRESET'))
        #Implement logic for switching out files without saving it yet
        ext = os.path.splitext(request.FILES.values()[0]._name)[1].split(".")[-1]
        original_filename = request.FILES.values()[0]._name
        size = request.FILES.values()[0]._size
        file_object = File(file_size=size, file_on_disk=DjFile(request.FILES.values()[0]), file_format=FileFormat.objects.get(extension=ext), original_filename = original_filename, preset=preset)
        file_object.save()
        return HttpResponse(json.dumps({
            "success": True,
            "filename": str(file_object),
            "object_id": file_object.pk
        }))

def file_create(request):
    if request.method == 'POST':
        ext = os.path.splitext(request.FILES.values()[0]._name)[1].split(".")[-1]
        size = request.FILES.values()[0]._size
        presets = FormatPreset.objects.filter(allowed_formats__extension__contains=ext)
        kind = presets.first().kind
        original_filename = request.FILES.values()[0]._name
        new_node = ContentNode(title=original_filename.split(".")[0], kind=kind, license_id=settings.DEFAULT_LICENSE, author=request.user.get_full_name())
        new_node.save()
        file_object = File(file_on_disk=DjFile(request.FILES.values()[0]), file_format=FileFormat.objects.get(extension=ext), original_filename = original_filename, contentnode=new_node, file_size=size)
        file_object.save()

        if kind.pk == content_kinds.VIDEO:
            extract_thumbnail_wrapper(file_object)
            file_object.preset_id = guess_video_preset_by_resolution(str(file_object.file_on_disk))
        elif presets.filter(supplementary=False).count() == 1:
            file_object.preset = presets.filter(supplementary=False).first()

        file_object.save()

        return HttpResponse(json.dumps({
            "success": True,
            "object_id": new_node.pk
        }))

def extract_thumbnail_wrapper(file_object):
    with tempfile.NamedTemporaryFile(suffix=".{}".format(file_formats.PNG)) as tempf:
        tempf.close()
        extract_thumbnail_from_video(str(file_object.file_on_disk), tempf.name, overwrite=True)
        filename = write_file_to_storage(open(tempf.name, 'rb'), name=tempf.name)
        checksum, ext = os.path.splitext(filename)
        file_location = generate_file_on_disk_name(checksum, filename)
        thumbnail_object = File(
            file_on_disk=DjFile(open(file_location, 'rb')),
            file_format_id=file_formats.PNG,
            original_filename = 'Extracted Thumbnail',
            contentnode=file_object.contentnode,
            file_size=os.path.getsize(file_location),
            preset_id=format_presets.VIDEO_THUMBNAIL,
        )
        thumbnail_object.save()
        return thumbnail_object

def compress_video_wrapper(file_object):
    with tempfile.TemporaryFile(suffix=".{}".format(file_formats.MP4)) as tempf:
        tempf.close()
        compress_video(str(file_object.file_on_disk), tempf.name, overwrite=True)
        filename = write_file_to_storage(open(tempf.name, 'rb'), name=tempf.name)
        checksum, ext = os.path.splitext(filename)
        file_location = generate_file_on_disk_name(checksum, filename)
        low_res_object = File(
            file_on_disk=DjFile(open(file_location, 'rb')),
            file_format_id=file_formats.MP4,
            original_filename = file_object.original_filename,
            contentnode=file_object.contentnode,
            file_size=os.path.getsize(file_location),
            preset_id=format_presets.VIDEO_LOW_RES,
        )
        low_res_object.save()
        return low_res_object

def create_tiled_image_wrapper(files, preset_id):
    random.shuffle(files)
    if len(files) >= 4:
        files = files[:4]
    elif len(files) >= 1:
        files = files[:1]

    with tempfile.TemporaryFile(suffix=".{}".format(file_formats.PNG)) as tempf:
        tempf.close()
        create_tiled_image(files, tempf.name)

        filename = write_file_to_storage(open(tempf.name, 'rb'), name=tempf.name)
        checksum, ext = os.path.splitext(filename)
        file_location = generate_file_on_disk_name(checksum, filename)
        thumbnail_object = File(
            file_on_disk = DjFile(open(file_location, 'rb')),
            file_format_id = file_formats.PNG,
            file_size = os.path.getsize(file_location),
            preset_id = preset_id,
        )
        thumbnail_object.save()
        return thumbnail_object

def generate_thumbnail(request):
    logging.debug("Entering the generate_thumbnail endpoint")

    if request.method != 'POST':
        raise HttpResponseBadRequest("Only POST requests are allowed on this endpoint.")
    else:
        data = json.loads(request.body)
        node = ContentNode.objects.get(pk=data["node_id"])

        files = []
        for n in node.get_descendants().all():
            file_locations = n.files.filter(file_format_id__in=[file_formats.PNG, file_formats.JPG, file_formats.JPEG]).values_list('file_on_disk', flat=True)
            files += [str(f) for f in file_locations]

        assert node.kind.pk == content_kinds.TOPIC, "Thumbnail generation for this kind is not supported."
        assert any(files), "No images available to generate thumbnail."

        thumbnail_object = None
        if node.kind.pk == content_kinds.TOPIC:
            thumbnail_object = create_tiled_image_wrapper(list(set(files)), format_presets.TOPIC_THUMBNAIL)
        return HttpResponse(json.dumps({
            "success": True,
            "file_id": thumbnail_object.pk if thumbnail_object else None
        }))


@csrf_exempt
def thumbnail_upload(request):
    if request.method == 'POST':
        fobj = request.FILES.values()[0]
        formatted_filename = write_file_to_storage(fobj)

        return HttpResponse(json.dumps({
            "success": True,
            "filename": formatted_filename,
            "file_url": generate_storage_url(formatted_filename),
        }))

def exercise_image_upload(request):

    if request.method == 'POST':
        node = ContentNode.objects.get(id=request.META.get('HTTP_NODE'))
        ext = os.path.splitext(request.FILES.values()[0]._name)[1].split(".")[-1] # gets file extension without leading period
        file_object = File(file_on_disk=request.FILES.values()[0], file_format=FileFormat.objects.get(extension=ext), contentnode=node)
        file_object.save()
        return HttpResponse(json.dumps({
            "success": True,
            "filename": file_object.file_on_disk.url,
        }))

def duplicate_nodes(request):
    logging.debug("Entering the copy_node endpoint")

    if request.method != 'POST':
        raise HttpResponseBadRequest("Only POST requests are allowed on this endpoint.")
    else:
        data = json.loads(request.body)

        try:
            nodes = data["nodes"]
            sort_order = data.get("sort_order") or 1
            target_parent = data["target_parent"]
            channel_id = data["channel_id"]
            new_nodes = []

            with transaction.atomic():
                for node_data in nodes:
                    new_node = _duplicate_node(node_data['id'], sort_order=sort_order, parent=target_parent, channel_id=channel_id)
                    new_nodes.append(new_node.pk)
                    sort_order+=1

        except KeyError:
            raise ObjectDoesNotExist("Missing attribute from data: {}".format(data))

        return HttpResponse(json.dumps({
            "success": True,
            "node_ids": " ".join(new_nodes)
        }))

def _duplicate_node(node, sort_order=None, parent=None, channel_id=None):
    if isinstance(node, int) or isinstance(node, basestring):
        node = ContentNode.objects.get(pk=node)

    original_channel = node.get_original_node().get_channel() if node.get_original_node() else None

    new_node = ContentNode.objects.create(
        title=node.title,
        description=node.description,
        kind=node.kind,
        license=node.license,
        parent=ContentNode.objects.get(pk=parent) if parent else None,
        sort_order=sort_order or node.sort_order,
        copyright_holder=node.copyright_holder,
        changed=True,
        original_node=node.original_node or node,
        cloned_source=node,
        original_channel_id = node.original_channel_id or original_channel.id if original_channel else None,
        source_channel_id = node.get_channel().id if node.get_channel() else None,
        original_source_node_id = node.original_source_node_id or node.node_id,
        source_node_id = node.node_id,
        author=node.author,
        content_id=node.content_id,
        extra_fields=node.extra_fields,
    )

    # add tags now
    for tag in node.tags.all():
        new_tag, is_new = ContentTag.objects.get_or_create(
            tag_name=tag.tag_name,
            channel_id=channel_id,
        )
        new_node.tags.add(new_tag)

    # copy file object too
    for fobj in node.files.all():
        fobj_copy = copy.copy(fobj)
        fobj_copy.id = None
        fobj_copy.contentnode = new_node
        fobj_copy.save()

    # copy assessment item object too
    for aiobj in node.assessment_items.all():
        aiobj_copy = copy.copy(aiobj)
        aiobj_copy.id = None
        aiobj_copy.contentnode = new_node
        aiobj_copy.save()
        for fobj in aiobj.files.all():
            fobj_copy = copy.copy(fobj)
            fobj_copy.id = None
            fobj_copy.assessment_item = aiobj_copy
            fobj_copy.save()

    for c in node.children.all():
        _duplicate_node(c, parent=new_node.id)

    return new_node


def move_nodes(request):
    logging.debug("Entering the move_nodes endpoint")

    if request.method != 'POST':
        raise HttpResponseBadRequest("Only POST requests are allowed on this endpoint.")
    else:
        data = json.loads(request.body)

        try:
            nodes = data["nodes"]
            target_parent = ContentNode.objects.get(pk=data["target_parent"])
            channel_id = data["channel_id"]
        except KeyError:
            raise ObjectDoesNotExist("Missing attribute from data: {}".format(data))

        with transaction.atomic():
            for n in nodes:
                node = ContentNode.objects.get(pk=n['id'])
                _move_node(node, parent=target_parent, sort_order=n['sort_order'], channel_id=channel_id)

        return HttpResponse(json.dumps({
            "success": True,
            "nodes": [n['id'] for n in nodes]
        }))

def _move_node(node, parent=None, sort_order=1, channel_id=None):
    node.parent = parent
    node.sort_order = sort_order
    node.changed = True
    descendants = node.get_descendants(include_self=True)
    node.save()

    for tag in ContentTag.objects.filter(tagged_content__in=descendants).distinct():
        # If moving from another channel
        if tag.channel_id != channel_id:
            t, is_new = ContentTag.objects.get_or_create(
                tag_name=tag.tag_name,
                channel_id=channel_id,
            )

            # Set descendants with this tag to correct tag
            for n in descendants.filter(tags=tag):
                n.tags.remove(tag)
                n.tags.add(t)

    return node

@csrf_exempt
def publish_channel(request):
    logging.debug("Entering the publish_channel endpoint")
    if request.method != 'POST':
        raise HttpResponseBadRequest("Only POST requests are allowed on this endpoint.")
    else:
        data = json.loads(request.body)

        try:
            channel_id = data["channel_id"]
        except KeyError:
            raise ObjectDoesNotExist("Missing attribute from data: {}".format(data))

        call_command("exportchannel", channel_id)

        return HttpResponse(json.dumps({
            "success": True,
            "channel": channel_id
        }))
