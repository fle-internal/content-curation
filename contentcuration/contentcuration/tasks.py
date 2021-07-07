from __future__ import absolute_import
from __future__ import unicode_literals

import logging
import time
from builtins import str

from celery import states
from celery.utils.log import get_task_logger
from django.conf import settings
from django.core.mail import EmailMessage
from django.db import IntegrityError
from django.db.utils import OperationalError
from django.template.loader import render_to_string
from django.utils.translation import gettext as _
from django.utils.translation import override

from contentcuration.celery import app
from contentcuration.models import Channel
from contentcuration.models import ContentNode
from contentcuration.models import Task
from contentcuration.models import User
from contentcuration.utils.csv_writer import write_user_csv
from contentcuration.utils.nodes import calculate_resource_size
from contentcuration.utils.nodes import generate_diff
from contentcuration.utils.publish import publish_channel
from contentcuration.utils.sync import sync_channel
from contentcuration.viewsets.sync.constants import CHANNEL
from contentcuration.viewsets.sync.constants import CONTENTNODE
from contentcuration.viewsets.sync.constants import COPYING_FLAG
from contentcuration.viewsets.sync.utils import generate_update_event
from contentcuration.viewsets.user import AdminUserFilter


logger = get_task_logger(__name__)


# if we're running tests, import our test tasks as well
if settings.RUNNING_TESTS:
    from .tasks_test import caught_error_test_task, error_test_task, progress_test_task, test_task


STATE_QUEUED = "QUEUED"


@app.task(bind=True, name="delete_node_task")
def delete_node_task(
    self,
    user_id,
    channel_id,
    node_id,
):
    deleted = False
    attempts = 0
    try:
        node = ContentNode.objects.get(id=node_id)
    except ContentNode.DoesNotExist:
        deleted = True

    try:
        while not deleted and attempts < 10:
            try:
                node.delete()
                deleted = True
            except OperationalError as e:
                if "deadlock detected" in e.args[0]:
                    pass
                else:
                    raise
    except Exception as e:
        self.report_exception(e)

    # TODO: Generate create event if failed?
    # if not deleted:
    #     return {"changes": [generate_create_event(node.pk, CONTENTNODE, node)]}


@app.task(bind=True, name="move_nodes_task")
def move_nodes_task(
    self,
    user_id,
    channel_id,
    target_id,
    node_id,
    position="last-child",
):
    node = ContentNode.objects.get(id=node_id)
    target = ContentNode.objects.get(id=target_id)

    moved = False
    attempts = 0
    try:
        while not moved and attempts < 10:
            try:
                node.move_to(
                    target,
                    position,
                )
                moved = True
            except OperationalError as e:
                if "deadlock detected" in e.args[0]:
                    pass
                else:
                    raise
    except Exception as e:
        self.report_exception(e)

    if not moved:
        return {"changes": [generate_update_event(node.pk, CONTENTNODE, {"parent": node.parent_id})]}


@app.task(bind=True, name="duplicate_nodes_task", track_progress=True)
def duplicate_nodes_task(
    self,
    user_id,
    channel_id,
    target_id,
    source_id,
    pk=None,
    position="last-child",
    mods=None,
    excluded_descendants=None,
):
    source = ContentNode.objects.get(id=source_id)
    target = ContentNode.objects.get(id=target_id)

    can_edit_source_channel = ContentNode.filter_edit_queryset(
        ContentNode.objects.filter(id=source_id), user=User.objects.get(id=user_id)
    ).exists()

    new_node = None

    try:
        new_node = source.copy_to(
            target,
            position,
            pk,
            mods,
            excluded_descendants,
            can_edit_source_channel=can_edit_source_channel,
            progress_tracker=self.progress,
        )
    except IntegrityError:
        # This will happen if the node has already been created
        # Pass for now and just return the updated data
        # Possible we might want to raise an error here, but not clear
        # whether this could then be a way to sniff for ids
        pass

    changes = []
    if new_node is not None:
        changes.append(generate_update_event(pk, CONTENTNODE, {COPYING_FLAG: False, "node_id": new_node.node_id}))

    return {"changes": changes}


@app.task(bind=True, name="export_channel_task", track_progress=True)
def export_channel_task(self, user_id, channel_id, version_notes="", language=settings.LANGUAGE_CODE):
    with override(language):
        channel = publish_channel(
            user_id,
            channel_id,
            version_notes=version_notes,
            send_email=True,
            progress_tracker=self.progress,
        )
    return {"changes": [
        generate_update_event(channel_id, CHANNEL, {"published": True, "primary_token": channel.get_human_token().token}),
        generate_update_event(channel.main_tree.pk, CONTENTNODE, {"published": True, "changed": False}),
    ]}


@app.task(bind=True, name="sync_channel_task", track_progress=True)
def sync_channel_task(
    self,
    user_id,
    channel_id,
    sync_attributes,
    sync_tags,
    sync_files,
    sync_assessment_items,
):
    channel = Channel.objects.get(pk=channel_id)
    sync_channel(
        channel,
        sync_attributes,
        sync_tags,
        sync_files,
        sync_tags,
        progress_tracker=self.progress,
    )


class CustomEmailMessage(EmailMessage):
    """
        jayoshih: There's an issue with the django postmark backend where
        _build_message attempts to attach files as base64. However,
        the django EmailMessage attach method makes all content with a text/*
        mimetype to be encoded as a string, causing `base64.b64encode(content)`
        to fail. This is a workaround to ensure that content is still encoded as
        bytes when it comes to encoding the attachment as base64
    """
    def attach(self, filename=None, content=None, mimetype=None):
        assert filename is not None
        assert content is not None
        assert mimetype is not None
        self.attachments.append((filename, content, mimetype))


@app.task(name="generateusercsv_task")
def generateusercsv_task(user_id, language=settings.LANGUAGE_CODE):
    with override(language):
        user = User.objects.get(pk=user_id)
        csv_path = write_user_csv(user)
        subject = render_to_string("export/user_csv_email_subject.txt", {})
        message = render_to_string(
            "export/user_csv_email.txt",
            {
                "legal_email": settings.POLICY_EMAIL,
                "user": user,
                "edit_channels": user.editable_channels.values("name", "id"),
                "view_channels": user.view_only_channels.values("name", "id"),
            },
        )

        email = CustomEmailMessage(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email])
        email.encoding = 'utf-8'
        email.attach_file(csv_path, mimetype="text/csv")

        email.send()


@app.task(name="deletetree_task")
def deletetree_task(tree_id):
    ContentNode.objects.filter(tree_id=tree_id).delete()


@app.task(name="getnodedetails_task")
def getnodedetails_task(node_id):
    node = ContentNode.objects.get(pk=node_id)
    return node.get_details()


@app.task(name="generatenodediff_task")
def generatenodediff_task(updated_id, original_id):
    return generate_diff(updated_id, original_id)


@app.task(name="calculate_user_storage_task")
def calculate_user_storage_task(user_id):
    try:
        user = User.objects.get(pk=user_id)
        user.set_space_used()
    except User.DoesNotExist:
        logging.error("Tried to calculate user storage for user with id {} but they do not exist".format(user_id))


@app.task(name="calculate_resource_size_task")
def calculate_resource_size_task(node_id, channel_id):
    node = ContentNode.objects.get(pk=node_id)
    size, _ = calculate_resource_size(node=node, force=True)
    return size


@app.task(name="sendcustomemails_task")
def sendcustomemails_task(subject, message, query):
    subject = render_to_string('registration/custom_email_subject.txt', {'subject': subject})
    recipients = AdminUserFilter(data=query).qs.distinct()

    for recipient in recipients:
        text = message.format(current_date=time.strftime("%A, %B %d"), current_time=time.strftime("%H:%M %Z"), **recipient.__dict__)
        text = render_to_string('registration/custom_email.txt', {'message': text})
        recipient.email_user(subject, text, settings.DEFAULT_FROM_EMAIL, )


type_mapping = {
    "duplicate-nodes": duplicate_nodes_task,
    "move-nodes": move_nodes_task,
    "delete-node": delete_node_task,
    "export-channel": export_channel_task,
    "sync-channel": sync_channel_task,
    "get-node-diff": generatenodediff_task,
    "calculate-user-storage": calculate_user_storage_task,
    "calculate-resource-size": calculate_resource_size_task,
}

if settings.RUNNING_TESTS:
    type_mapping.update(
        {
            "test": test_task,
            "error-test": error_test_task,
            "caught-error-test": caught_error_test_task,
            "progress-test": progress_test_task,
        }
    )


def get_or_create_async_task(task_name, user, **task_args):
    """
    :param task_name: Name of the task function (omitting the word 'task', and with dashes in place of underscores)
    :param user: User object of the user performing the operation
    :param task_args: A dictionary of keyword arguments to be passed down to the task, must be JSON serializable.
    :return: Returns the Task model object
    """
    if task_name not in type_mapping:
        raise KeyError("Need to define task in type_mapping first.")

    if user is None or not isinstance(user, User):
        raise TypeError("All tasks must be assigned to a user.")

    qs = Task.objects.filter(
        task_type=task_name,
        status__in=[STATE_QUEUED, states.PENDING, states.RECEIVED, states.STARTED],
        channel_id=task_args.get("channel_id", None),
        metadata={"args": task_args},
    )

    try:
        task_info = qs[0]
    except IndexError:
        task_info = None

    if task_info is None:
        _, task_info = create_async_task(task_name, user, **task_args)

    return task_info


def create_async_task(task_name, user, apply_async=True, **task_args):
    """
    Starts a long-running task that runs asynchronously using Celery. Also creates a Task object that can be used by
    Studio to keep track of the Celery task's status and progress.

    This function should only be used to start Celery tasks that are user-facing, that is, that Studio users are
    aware of and want information on. DB maintenance tasks and other similar operations should simply start a
    Celery task manually.

    The task name must be registered in the type_mapping dictionary before this function can be used to initiate
    the task.

    :param task_name: Name of the task function (omitting the word 'task', and with dashes in place of underscores)
    :param user: User object of the user performing the operation
    :param apply_async: Boolean whether to call the Task asynchronously (the default)
    :param task_args: A dictionary of keyword arguments to be passed down to the task, must be JSON serializable.
    :return: a tuple of the Task object and a dictionary containing information about the created task.
    """
    if task_name not in type_mapping:
        raise KeyError("Need to define task in type_mapping first.")

    if user is None or not isinstance(user, User):
        raise TypeError("All tasks must be assigned to a user.")

    async_task = type_mapping[task_name]
    task_info = Task.objects.create(
        task_type=task_name,
        status=STATE_QUEUED,
        user=user,
        channel_id=task_args.get("channel_id", None),
        metadata={"args": task_args},
    )
    task_sig = async_task.signature(
        task_id=str(task_info.task_id),
        kwargs=task_args,
    )

    if apply_async:
        task = task_sig.apply_async()
    else:
        task = task_sig.apply()

    # If there was a failure to create the task, the apply_async call will return failed, but
    # checking the status will still show PENDING. So make sure we write the failure to the
    # db directly so the frontend can know of the failure.
    if task.status == states.FAILURE:
        # Error information may have gotten added to the Task object during the call.
        task_info.refresh_from_db()
        logging.error("Task failed to start, please check Celery status.")
        task_info.status = states.FAILURE
        error_data = {
            "message": _("Unknown error starting task. Please contact support.")
        }
        # The Celery on_failure handler may also add a traceback, so make sure
        # we only create a new error object if one doesn't already exist.
        if "error" not in task_info.metadata:
            task_info.metadata["error"] = {}
        task_info.metadata["error"].update(error_data)
        task_info.save()

    return task, task_info
