import os

from django.apps import AppConfig
from django.conf import settings


class ContentConfig(AppConfig):
    name = 'contentcuration'

    def ready(self):
        pass
