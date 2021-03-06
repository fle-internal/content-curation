import os
import traceback as _traceback

from celery import states
from celery.signals import after_task_publish
from celery.signals import task_failure
from celery.signals import task_postrun
from celery.signals import task_prerun
from celery.signals import task_success
from celery.utils.log import get_task_logger
from django.core.exceptions import ObjectDoesNotExist
from django.db import connection
from django.db.utils import InterfaceError

from contentcuration.models import Task

# because Celery connects signals upon import, we don't want to put signals into other modules that may be
# imported multiple times. Instead, we follow the advice here and use AppConfig.init to import the module:
# https://stackoverflow.com/questions/7115097/the-right-place-to-keep-my-signals-py-file-in-a-django-project/21612050#21612050

logger = get_task_logger(__name__)


def check_connection():
    """
    Due to known and seemingly unresolved issue with celery,
    if a postgres connection drops and becomes unusable, it causes
    failure of tasks and all their signal handlers that use the DB:
    https://github.com/celery/celery/issues/621
    """
    try:
        connection.cursor()
    except InterfaceError:
        connection.close_if_unusable_or_obsolete()
        connection.connect()


@task_prerun.connect
def prerun(sender, **kwargs):
    """
    Before a task is run, make sure that the connection works
    """
    check_connection()


@task_postrun.connect
def postrun(sender, **kwargs):
    """
    After a task has been run, make sure that the connection works
    """
    check_connection()


@after_task_publish.connect
def before_start(sender, headers, **kwargs):
    """
    Create a Task object before the task actually started,
    set the task object status to be PENDING, with the signal
    after_task_publish to indicate that the task has been
    sent to the broker.

    Note: we do not test the connection here, as this signal
    is processed by the worker parent process that sent the task
    not by the worker process.
    """
    task_id = headers["id"]

    try:
        task = Task.objects.get(task_id=task_id)
        task.status = states.PENDING
        task.save()
        logger.info("Task object {} updated with status PENDING.".format(task_id))
    except ObjectDoesNotExist:
        # If the object doesn't exist, that likely means the task was created outside of
        # create_async_task
        pass


@task_failure.connect
def on_failure(sender, task_id, traceback, **kwargs):
    # Ensure that the connection still works before we attempt
    # to access the database here. See function comment for more details.
    check_connection()
    try:
        task = Task.objects.get(task_id=task_id)
        task.status = states.FAILURE
        if 'error' not in task.metadata:
            task.metadata['error'] = {}
        task.metadata['error'].update(traceback=_traceback.format_tb(traceback))
        task.save()
    except ObjectDoesNotExist:
        # If the object doesn't exist, that likely means the task was created outside of
        # create_async_task
        pass


@task_success.connect
def on_success(sender, result, **kwargs):
    # Ensure that the connection still works before we attempt
    # to access the database here. See function comment for more details.
    check_connection()
    try:
        logger.info("on_success called, process is {}".format(os.getpid()))
        task_id = sender.request.id
        task = Task.objects.get(task_id=task_id)
        task.status = states.SUCCESS
        task.metadata['result'] = result
        task.save()
        logger.info("Task with ID {} succeeded".format(task_id))
    except ObjectDoesNotExist:
        # If the object doesn't exist, that likely means the task was created outside of
        # create_async_task
        pass
