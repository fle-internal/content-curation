import copy
import json
import logging
import os
import uuid
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Q, Case, When, Value, IntegerField, Max, Sum
from rest_framework.renderers import JSONRenderer
from contentcuration.utils.files import duplicate_file
from contentcuration.models import File, ContentNode, ContentTag, AssessmentItem
from contentcuration.serializers import ContentNodeSerializer, ContentNodeEditSerializer, SimplifiedContentNodeSerializer
from le_utils.constants import format_presets, content_kinds, file_formats, licenses

def get_total_size(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        sizes = ContentNode.objects.prefetch_related('assessment_items').prefetch_related('files').prefetch_related('children')\
                    .filter(id__in=data).get_descendants(include_self=True)\
                    .aggregate(resource_size=Sum('files__file_size'), assessment_size=Sum('assessment_items__files__file_size'))

        return HttpResponse(json.dumps({'success':True, 'size': (sizes['resource_size'] or 0) + (sizes['assessment_size'] or 0)}))

def delete_nodes(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        nodes = ContentNode.objects.filter(pk__in=data['nodes']).delete()
        return HttpResponse({'success':True})

def get_node_descendants(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        nodes = ContentNode.objects.filter(pk__in=data).get_descendants(include_self=True).values_list('id', flat=True)
        return HttpResponse(json.dumps({'success':True, "node_ids": " ".join(nodes)}))


def get_nodes_by_ids(request):
    if request.method == 'POST':
        nodes = ContentNode.objects.prefetch_related('children').prefetch_related('files')\
                .prefetch_related('assessment_items').prefetch_related('tags').filter(pk__in=json.loads(request.body))\
                .defer('node_id', 'original_source_node_id', 'source_node_id', 'content_id', 'original_channel_id', 'source_channel_id', 'source_id', 'source_domain', 'created', 'modified')
        return HttpResponse(JSONRenderer().render(ContentNodeSerializer(nodes, many=True).data))

def get_nodes_by_ids_simplified(request):
    if request.method == 'POST':
        nodes = ContentNode.objects.prefetch_related('children').filter(pk__in=json.loads(request.body))
        return HttpResponse(JSONRenderer().render(SimplifiedContentNodeSerializer(nodes, many=True).data))

def get_nodes_by_ids_complete(request):
    if request.method == 'POST':
        nodes = ContentNode.objects.prefetch_related('children').prefetch_related('files')\
                .prefetch_related('assessment_items').prefetch_related('tags').filter(pk__in=json.loads(request.body))
        return HttpResponse(JSONRenderer().render(ContentNodeEditSerializer(nodes, many=True).data))

def duplicate_nodes(request):
    logging.debug("Entering the copy_node endpoint")

    if request.method != 'POST':
        return HttpResponseBadRequest("Only POST requests are allowed on this endpoint.")
    else:
        data = json.loads(request.body)

        try:
            nodes = data["nodes"]
            sort_order = data.get("sort_order") or 1
            target_parent = data["target_parent"]
            channel_id = data["channel_id"]
            new_nodes = []

            with transaction.atomic():
                with ContentNode.objects.disable_mptt_updates():
                    for node_data in nodes:
                        new_node = _duplicate_node_bulk(node_data['id'], sort_order=sort_order, parent=target_parent, channel_id=channel_id)
                        new_nodes.append(new_node.pk)
                        sort_order+=1

        except KeyError:
            raise ObjectDoesNotExist("Missing attribute from data: {}".format(data))

        serialized = ContentNodeEditSerializer(ContentNode.objects.filter(pk__in=new_nodes), many=True).data
        return HttpResponse(JSONRenderer().render(serialized))

def _duplicate_node_bulk(node, sort_order=None, parent=None, channel_id=None):
    if isinstance(node, int) or isinstance(node, basestring):
        node = ContentNode.objects.get(pk=node)

    # keep track of the in-memory models so that we can bulk-create them at the end (for efficiency)
    to_create = {
        "nodes": [],
        "node_files": [],
        "assessment_files": [],
        "assessments": [],
    }

    # perform the actual recursive node cloning
    new_node = _duplicate_node_bulk_recursive(node=node, sort_order=sort_order, parent=parent, channel_id=channel_id, to_create=to_create)

    # create nodes, one level at a time, starting from the top of the tree (so that we have IDs to pass as "parent" for next level down)
    for node_level in to_create["nodes"]:
        for node in node_level:
            node.parent_id = node.parent.id
        ContentNode.objects.bulk_create(node_level)
        for node in node_level:
            for tag in node._meta.tags_to_add:
                node.tags.add(tag)

    # rebuild MPTT tree for this channel (since we're inside "disable_mptt_updates", and bulk_create doesn't trigger rebuild signals anyway)
    ContentNode.objects.partial_rebuild(to_create["nodes"][0][0].tree_id)

    ai_node_ids = []

    # create each of the assessment items
    for a in to_create["assessments"]:
        a.contentnode_id = a.contentnode.id
        ai_node_ids.append(a.contentnode_id)
    AssessmentItem.objects.bulk_create(to_create["assessments"])

    # build up a mapping of contentnode/assessment_id onto assessment item IDs, so we can point files to them correctly after
    aid_mapping = {}
    for a in AssessmentItem.objects.filter(contentnode_id__in=ai_node_ids):
        aid_mapping[a.contentnode_id + ":" + a.assessment_id] = a.id

    # create the file objects, for both nodes and assessment items
    for f in to_create["node_files"]:
        f.contentnode_id = f.contentnode.id
    for f in to_create["assessment_files"]:
        f.assessment_item_id = aid_mapping[f.assessment_item.contentnode_id + ":" + f.assessment_item.assessment_id]
    File.objects.bulk_create(to_create["node_files"] + to_create["assessment_files"])

    return new_node

def _duplicate_node_bulk_recursive(node, sort_order, parent, channel_id, to_create, level=0):

    if isinstance(node, int) or isinstance(node, basestring):
        node = ContentNode.objects.get(pk=node)

    if isinstance(parent, int) or isinstance(parent, basestring):
        parent = ContentNode.objects.get(pk=parent)

    # clone the model (in-memory) and update the fields on the cloned model
    new_node = copy.copy(node)
    new_node.id = None
    new_node.tree_id = parent.tree_id
    new_node.parent = parent
    new_node.sort_order = sort_order or node.sort_order
    new_node.changed = True
    new_node.cloned_source = node
    new_node.source_channel_id = node.get_channel().id if node.get_channel() else None
    new_node.node_id = uuid.uuid4().hex
    new_node.source_node_id = node.node_id

    # store the new unsaved model in a list, at the appropriate level, for later creation
    while len(to_create["nodes"]) <= level:
        to_create["nodes"].append([])
    to_create["nodes"][level].append(new_node)

    # find or create any tags that are needed, and store them under _meta on the node so we can add them to it later
    new_node._meta.tags_to_add = []
    for tag in node.tags.all():
        new_tag, is_new = ContentTag.objects.get_or_create(
            tag_name=tag.tag_name,
            channel_id=channel_id,
        )
        new_node._meta.tags_to_add.append(new_tag)

    # clone the file objects for later saving
    for fobj in node.files.all():
        f = duplicate_file(fobj, node=new_node, save=False)
        to_create["node_files"].append(f)

    # copy assessment item objects, and associated files
    for aiobj in node.assessment_items.prefetch_related("files").all():
        aiobj_copy = copy.copy(aiobj)
        aiobj_copy.id = None
        aiobj_copy.contentnode = new_node
        to_create["assessments"].append(aiobj_copy)
        for fobj in aiobj.files.all():
            f = duplicate_file(fobj, assessment_item=aiobj_copy, save=False)
            to_create["assessment_files"].append(f)

    # recurse down the tree and clone the children
    for child in node.children.all():
        _duplicate_node_bulk_recursive(node=child, sort_order=None, parent=new_node, channel_id=channel_id, to_create=to_create, level=level+1)

    return new_node

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
        duplicate_file(fobj, node=new_node)

    # copy assessment item object too
    for aiobj in node.assessment_items.all():
        aiobj_copy = copy.copy(aiobj)
        aiobj_copy.id = None
        aiobj_copy.contentnode = new_node
        aiobj_copy.save()
        for fobj in aiobj.files.all():
            duplicate_file(fobj, assessment_item=aiobj_copy)

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
            min_order = data.get("min_order") or 0
            max_order = data.get("max_order") or min_order + len(nodes)

        except KeyError:
            raise ObjectDoesNotExist("Missing attribute from data: {}".format(data))

        all_ids = []
        with transaction.atomic():
            with ContentNode.objects.delay_mptt_updates():
                for n in nodes:
                    min_order = min_order + float(max_order - min_order) / 2
                    node = ContentNode.objects.get(pk=n['id'])
                    _move_node(node, parent=target_parent, sort_order=min_order, channel_id=channel_id)
                    all_ids.append(n['id'])

        serialized = ContentNodeEditSerializer(ContentNode.objects.filter(pk__in=all_ids), many=True).data
        return HttpResponse(JSONRenderer().render(serialized))

def _move_node(node, parent=None, sort_order=None, channel_id=None):
    node.parent = parent or node.parent
    node.sort_order = sort_order or node.sort_order
    node.changed = True
    descendants = node.get_descendants(include_self=True)
    node.save()

    for tag in ContentTag.objects.filter(tagged_content__in=descendants).distinct():
        # If moving from another channel
        if tag.channel_id != channel_id:
            t, is_new = ContentTag.objects.get_or_create(tag_name=tag.tag_name, channel_id=channel_id)

            # Set descendants with this tag to correct tag
            for n in descendants.filter(tags=tag):
                n.tags.remove(tag)
                n.tags.add(t)

    return node
