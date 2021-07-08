import logging as logmodule
import re
import sys

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import Error as DBError
from le_utils.constants import content_kinds
from le_utils.constants import file_formats
from le_utils.constants import format_presets
from le_utils.constants import licenses

from contentcuration.models import ContentNode
from contentcuration.models import ContentTag
from contentcuration.models import Invitation
from contentcuration.models import License
from contentcuration.models import MultipleObjectsReturned
from contentcuration.models import PrerequisiteContentRelationship
from contentcuration.utils.db_tools import create_channel
from contentcuration.utils.db_tools import create_contentnode
from contentcuration.utils.db_tools import create_exercise
from contentcuration.utils.db_tools import create_file
from contentcuration.utils.db_tools import create_topic
from contentcuration.utils.db_tools import create_user
from contentcuration.utils.files import duplicate_file
from contentcuration.utils.minio_utils import ensure_storage_bucket_public
from contentcuration.utils.publish import publish_channel

logmodule.basicConfig()
logging = logmodule.getLogger(__name__)

DESCRIPTION = """
Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt
ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco
laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in
voluptate velit esse cillum dolore eu fugiat nulla pariatur.
"""
LICENSE = licenses.SPECIAL_PERMISSIONS
LICENSE_DESCRIPTION = "Sample text for content with special permissions"
TAGS = ["Tag 1", "Tag 2", "Tag 3"]
SORT_ORDER = 0


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('--email', dest="email", default="a@a.com")
        parser.add_argument('--password', dest="password", default="a")

    def handle(self, *args, **options):
        # Validate email
        email = options["email"]
        password = options["password"]
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            print("{} is not a valid email".format(email))
            sys.exit()

        # create the minio bucket
        ensure_storage_bucket_public()

        # create the cache table
        try:
            call_command("createcachetable")
        except DBError as e:
            logging.error('Error creating cache table: {}'.format(str(e)))

        # Run migrations
        call_command('migrate')

        # Run loadconstants
        call_command('loadconstants')

        # Set up user as admin
        admin = create_user(email, password, "Admin", "User", admin=True)

        # Create other users
        user1 = create_user("user@a.com", "a", "User", "A")
        user2 = create_user("user@b.com", "b", "User", "B")
        user3 = create_user("user@c.com", "c", "User", "C")

        # Create channels

        channel1 = create_channel("Published Channel", DESCRIPTION, editors=[admin], bookmarkers=[user1, user2], public=True)
        channel2 = create_channel("Ricecooker Channel", DESCRIPTION, editors=[admin, user1], bookmarkers=[user2], viewers=[user3])
        channel3 = create_channel("Empty Channel", editors=[user3], viewers=[user2])
        channel4 = create_channel("Imported Channel", editors=[admin])

        # Invite admin to channel 3
        try:
            invitation, _new = Invitation.objects.get_or_create(
                invited=admin,
                sender=user3,
                channel=channel3,
                email=admin.email,
            )
            invitation.share_mode = "edit"
            invitation.save()
        except MultipleObjectsReturned:
            # we don't care, just continue
            pass

        # Create pool of tags
        tags = []
        for t in TAGS:
            tag, _new = ContentTag.objects.get_or_create(tag_name=t, channel=channel1)

        # Generate file objects
        document_file = create_file("Sample Document", format_presets.DOCUMENT, file_formats.PDF, user=admin)
        video_file = create_file("Sample Video", format_presets.VIDEO_HIGH_RES, file_formats.MP4, user=admin)
        subtitle_file = create_file("Sample Subtitle", format_presets.VIDEO_SUBTITLE, file_formats.VTT, user=admin)
        audio_file = create_file("Sample Audio", format_presets.AUDIO, file_formats.MP3, user=admin)
        html5_file = create_file("Sample HTML", format_presets.HTML5_ZIP, file_formats.HTML5, user=admin)

        # Populate channel 1 with content
        generate_tree(channel1.main_tree, document_file, video_file, subtitle_file, audio_file, html5_file, user=admin, tags=tags)

        # Populate channel 2 with staged content
        channel2.ricecooker_version = "0.0.0"
        channel2.save()
        generate_tree(channel2.staging_tree, document_file, video_file, subtitle_file, audio_file, html5_file, user=admin, tags=tags)

        # Import content from channel 1 into channel 4
        channel1.main_tree.children.first().copy_to(channel4.main_tree)

        # Get validation to be reflected in nodes properly
        ContentNode.objects.all().update(complete=True)
        call_command('mark_incomplete')

        # Mark this node as incomplete even though it is complete
        # for testing purposes
        node = ContentNode.objects.get(tree_id=channel1.main_tree.tree_id, title="Sample Audio")
        node.complete = False
        node.save()

        # Publish
        publish_channel(admin.id, channel1.pk)

        # Add nodes to clipboard in legacy way
        legacy_clipboard_nodes = channel1.main_tree.get_children()
        for legacy_node in legacy_clipboard_nodes:
            legacy_node.copy_to(target=user1.clipboard_tree)

        print("\n\n\nSETUP DONE: Log in as admin to view data (email: {}, password: {})\n\n\n".format(email, password))


def generate_tree(root, document, video, subtitle, audio, html5, user=None, tags=None):
    topic1 = create_topic("Topic 1", root, description=DESCRIPTION)
    topic2 = create_topic("Topic 2", root)
    create_topic("Topic 3", topic2, description=DESCRIPTION)
    create_topic("Topic 4", topic2, description=DESCRIPTION)

    # Add files to topic 1
    license_id = License.objects.get(license_name=LICENSE).pk
    topic1_video_node = create_contentnode("Sample Video", topic1, video, content_kinds.VIDEO, license_id, user=user, tags=tags)
    duplicate_file(subtitle, node=topic1_video_node)

    topic1_document_node = create_contentnode("Sample Document", topic1, document, content_kinds.DOCUMENT, license_id, user=user, tags=tags)
    topic1_audio_node = create_contentnode("Sample Audio", topic1, audio, content_kinds.AUDIO, license_id, user=user, tags=tags)
    topic1_html5_node = create_contentnode("Sample HTML", topic1, html5, content_kinds.HTML5, license_id, user=user, tags=tags)
    topic1_exercise_node = create_exercise("Sample Exercise", topic1, license_id, user=user)
    create_exercise("Sample Empty Exercise", topic1, license_id, user=user, empty=True)

    # Setup pre/post-requisites around Exercise node
    # Topic 1 Video -> Topic 1 Document -> Topic 1 Exercise -> Topic 1 Audio -> Topic 1 Html5
    PrerequisiteContentRelationship.objects.create(target_node_id=topic1_document_node.id, prerequisite_id=topic1_video_node.id)
    PrerequisiteContentRelationship.objects.create(target_node_id=topic1_exercise_node.id, prerequisite_id=topic1_document_node.id)
    PrerequisiteContentRelationship.objects.create(target_node_id=topic1_audio_node.id, prerequisite_id=topic1_exercise_node.id)
    PrerequisiteContentRelationship.objects.create(target_node_id=topic1_html5_node.id, prerequisite_id=topic1_audio_node.id)
