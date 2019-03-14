from base import BaseAPITestCase

from contentcuration.models import Task
from contentcuration.tasks import create_async_task, non_async_test_task
# from celery.contrib.testing.worker import start_worker
# from contentcuration.celery import app


class AsyncTaskTestCase(BaseAPITestCase):
    """
    These tests check that creating and updating Celery tasks using the create_async_task function result in
    an up-to-date Task object with the latest status and information about the task.
    """
    task_url = '/api/task'

    def test_asynctask_reports_success(self):
        """
        Tests that when an async task is created and completed, the Task object has a status of 'SUCCESS' and
        contains the return value of the task.
        """
        metadata = {'test': True}
        task_options = {
            'user_id': self.user.pk,
            'task_type': 'asynctask',
            'metadata': metadata
        }
        task, task_info = create_async_task('test', task_options)
        self.assertTrue(Task.objects.filter(metadata__test=True).count()==1)
        self.assertEqual(task_info.user, self.user)
        self.assertEqual(task_info.task_type, 'test')
        self.assertEqual(task_info.is_progress_tracking, False)
        result = task.get()
        self.assertEqual(Task.objects.get(task_id=task.id).metadata['result'], 42)
        self.assertEqual(Task.objects.get(task_id=task.id).status, 'SUCCESS')

    def test_asynctask_reports_progress(self):
        """
        Test that we can retrieve task progress via the Task API.
        """
        metadata = {'test': True}
        task_options = {
            'user_id': self.user.pk,
            'task_type': 'asynctask',
            'metadata': metadata
        }
        task, task_info = create_async_task('progress-test', task_options)
        self.assertTrue(Task.objects.filter(metadata__test=True).count()==1)
        result = task.get()
        self.assertEqual(result, 42)
        self.assertEqual(Task.objects.get(task_id=task.id).status, 'SUCCESS')

        # progress is retrieved dynamically upon calls to get the task info, so
        # use an API call rather than checking the db directly for progress.
        url = '{}/{}'.format(self.task_url, task_info.id)
        response = self.get(url)
        self.assertEqual(response.data['status'], 'SUCCESS')
        self.assertEqual(response.data['task_type'], 'progress-test')
        self.assertEqual(response.data['metadata']['progress'], 100)
        self.assertEqual(response.data['metadata']['result'], 42)

    def test_asynctask_reports_error(self):
        """
        Tests that if a task fails with an error, that the error information is stored in the Task object for later
        retrieval and analysis.
        """
        metadata = {'test': True}
        task_options = {
            'user_id': self.user.pk,
            'task_type': 'asynctask',
            'metadata': metadata
        }
        task, task_info = create_async_task('error-test', task_options)

        task = Task.objects.get(task_id=task.id)
        self.assertEqual(task.status, 'FAILURE')
        self.assertTrue('error' in task.metadata)

        error = task.metadata['error']
        self.assertItemsEqual(list(error.keys()), ['task_args', 'task_kwargs', 'traceback'])
        self.assertEqual(len(error['task_args']), 0)
        self.assertEqual(len(error['task_kwargs']), 0)
        traceback_string = '\n'.join(error['traceback'])
        self.assertTrue("Exception" in traceback_string)
        self.assertTrue("I'm sorry Dave, I'm afraid I can't do that." in traceback_string)

    def test_only_create_async_task_creates_task_entry(self):
        """
        Test that we don't add a Task entry when we create a new Celery task outside of the create_async_task API.
        """

        task = non_async_test_task.apply_async()

        result = task.get()
        self.assertEquals(result, 42)
        self.assertEquals(Task.objects.filter(task_id=task.id).count(), 0)
