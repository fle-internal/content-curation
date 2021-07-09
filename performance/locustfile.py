#!/usr/bin/env python
import json
import os
import time
from random import choice

from locust import HttpUser
from locust import task
from locust import TaskSet
try:
    import urllib.request as urlrequest
except ImportError:
    import urllib as urlrequest

USERNAME = os.getenv("LOCUST_USERNAME") or "a@a.com"
PASSWORD = os.getenv("LOCUST_PASSWORD") or "a"


class BaseTaskSet(TaskSet):
    max_wait = 60000

    def _login(self):
        """
        Helper function to log in the user to the current session.
        """
        resp = self.client.get("/accounts/")
        csrf = resp.cookies["csrftoken"]
        formdata = {
            "username": USERNAME,
            "password": PASSWORD,
        }
        self.client.post(
            "/accounts/login/",
            data=json.dumps(formdata),
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "referer": "{}/accounts/".format(self.client.base_url),
                "X-CSRFToken": csrf
            }
        )

    def _run_async_task(self, url, channel_id, data):
        copy_resp = self.client.post(url,
                                     data=json.dumps(data),
                                     headers={
                                         "content-type": "application/json",
                                         'X-CSRFToken': self.client.cookies.get('csrftoken'),
                                         'Referer': self.client.base_url
                                     })
        copy_resp_data = copy_resp.json()
        task_id = copy_resp_data["id"]
        finished = False
        time_elapsed = 0
        status = 'QUEUED'
        while not finished:
            time.sleep(1)
            time_elapsed += 1
            task_resp = self.client.get("/api/task/{}?channel_id={}".format(task_id, channel_id))
            task_data = task_resp.json()
            if task_data["status"] in ["SUCCESS", "FAILED"] or time_elapsed > 120:
                finished = True
                status = task_data["status"]

        return status


class ChannelListPage(BaseTaskSet):
    """
    Task to explore different channels lists
    """
    def on_start(self):
        self._login()

    @task
    def channel_list(self):
        """
        Load the channel page and the important endpoints.
        """
        self.client.get("/channels/")


class ChannelPage(BaseTaskSet):
    """
    Task to open and view a channel, including its topics and nodes
    """
    def on_start(self):
        self._login()

    def get_first_public_channel_id(self):
        """
        Returns the id of the first available public channel
        :returns: id of the first available public channel or None if there are not public channels
        """
        resp = self.client.get("/api/channels?public=true").json()
        try:
            channel_id = resp[0]['id']
        except IndexError:
            channel_id = None
        return channel_id

    def get_first_edit_channel_id(self):
        """
        Returns the id of the first available public channel
        :returns: id of the first available public channel or None if there are not public channels
        """
        resp = self.client.get("/api/channels?edit=true").json()
        try:
            channel_id = resp[0]['id']
        except IndexError:
            channel_id = None
        return channel_id

    def get_topic_id(self, channel_id, random=False):
        """
        Returns the id of a randomly selected topic for the provided channel_id
        :param: channel_id: id of the channel where the topic must be found
        :returns: id of the selected topic
        """
        channel_resp = self.client.get('/api/channel/{}'.format(channel_id)).json()
        children = channel_resp['main_tree']['children']
        topic_id = children[0]
        if random:
            topic_id = choice(children)
        return topic_id

    def get_resource_id(self, topic_id, random=False):
        """
        Returns the id of a randoly selected resource for the provided topic_id
        :param: topic_id: id of the topic where the resource must be found
        :returns: id of the selected resource
        """
        nodes_resp = self.client.get('/api/contentnodes?parent={}'.format(topic_id)).json()
        try:
            while nodes_resp[0]['kind'] == 'topic':
                nodes = nodes_resp[0]['children']
                nodes_resp = self.client.get('/api/contentnodes?ids={}'.format(','.join(nodes))).json()
            node_id = nodes_resp[0]['id']
            if random:
                node_id = choice(nodes_resp)['id']
            return node_id
        except IndexError:
            return None

    @task
    def open_channel(self, channel_id=None):
        """
        Open to edit a channel, if channel_id is None it opens the first public channel
        """
        if not channel_id:
            channel_id = self.get_first_public_channel_id()
        if channel_id:
            self.client.get('/channels/{}'.format(channel_id))

    # This is the most frequently hit scenario outside of ricecooker usage, so give it more weight.
    @task(3)
    def open_subtopic(self, channel_id=None, topic_id=None):
        """
        Open  a topic, if channel_id is None it opens the first public channel
        """
        if not channel_id:
            channel_id = self.get_first_public_channel_id()
        if channel_id and not topic_id:
            topic_id = self.get_topic_id(channel_id)
        if topic_id:
            self.get_resource_id(topic_id)

    @task
    def preview_content_item(self, content_id=None, random=False):
        """
        Do request on all the files for a content item.
        If content_id is not provided it will fetch a random content
        """
        if not content_id:
            channel_id = self.get_first_public_channel_id()
            topic_id = self.get_topic_id(channel_id, random=random)
            content_id = self.get_resource_id(topic_id, random=random)
            if content_id:
                resp = self.client.get('/api/contentnode/{}'.format(content_id)).json()
                if 'files' in resp[0]:
                    for resource in resp[0]['files']:
                        storage_url = resource['storage_url']
                        print("Requesting resource {}".format(storage_url))
                        urlrequest.urlopen(storage_url).read()


class ChannelEdit(BaseTaskSet):
    # This flag was recommended to ensure on_stop is always called, but it seems not to be enough
    # on its own to ensure this behavior. Leaving as it's possible this is needed, but along with
    # something else.
    always_run_on_stop = True

    def on_start(self):
        self._login()
        self.created_channels = []

    def on_stop(self):
        # FIXME: This is not being called when the run completes, need to find out why.
        # Note that until this is fixed, any channel with the name "Locust Test Channel"
        # in the database needs to be manually deleted.
        for channel in self.created_channels:
            self.client.delete(
                "/api/channel/{}/".format(channel),
                headers={
                    "content-type": "application/json",
                    'X-CSRFToken': self.client.cookies.get('csrftoken'),
                }
            )

            # TODO: check for deletion issues and report so that manual cleanup can be performed if needed.

    @task(6)
    def create_channel(self):
        """
        Load the channel page and the important endpoints.
        """
        formdata = {
            "name": "Locust Test Channel",
            "description": "Description of locust test channel",
            "thumbnail_url": '/static/img/kolibri_placeholder.png',
            "count": 0,
            "size": 0,
            "published": False,
            "view_only": False,
            "viewers": [],
            "content_defaults": {},
            "pending_editors": []
        }
        self.client.post(
            "/api/channel",
            data=json.dumps(formdata),
            headers={
                "content-type": "application/json",
                'X-CSRFToken': self.client.cookies.get('csrftoken'),
                'Referer': self.client.base_url
            }
        )


class LoginPage(BaseTaskSet):
    tasks = [ChannelListPage, ChannelPage, ChannelEdit]

    # This is by far our most hit endpoint, over 50% of all calls, so
    # weight it accordingly.
    @task(10)
    def loginpage(self):
        """
        Visit the login page and the i18n endpoints without logging in.
        """
        self.client.get("/accounts/")


class StudioDesktopBrowserUser(HttpUser):
    tasks = [LoginPage, ChannelListPage]
    min_wait = 5000
    max_wait = 20000
    host = os.getenv("LOCUST_URL") or "http://localhost:8080"
