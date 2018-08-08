from django.core.management import call_command
from django.test import TestCase

from contentcuration.utils import minio_utils
from rest_framework.test import APITestCase

class StudioTestCase(TestCase):

    @classmethod
    def setUpClass(cls):
        super(StudioTestCase, cls).setUpClass()
        call_command('loadconstants')

    def setUp(self):
        minio_utils.ensure_storage_bucket_public()

    def tearDown(self):
        minio_utils.ensure_bucket_deleted()

class StudioAPITestCase(APITestCase):

    @classmethod
    def setUpClass(cls):
        super(StudioAPITestCase, cls).setUpClass()
        call_command('loadconstants')

    def setUp(self):
        minio_utils.ensure_storage_bucket_public()

    def tearDown(self):
        minio_utils.ensure_bucket_deleted()
