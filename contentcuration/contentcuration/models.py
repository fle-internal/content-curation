import functools
import hashlib
import json
import logging
import os
import urllib.parse
import uuid
from datetime import datetime

import pytz
from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.cache import cache
from django.core.exceptions import MultipleObjectsReturned
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.files.storage import FileSystemStorage
from django.core.mail import send_mail
from django.db import IntegrityError
from django.db import models
from django.db.models import Count
from django.db.models import Exists
from django.db.models import Index
from django.db.models import IntegerField
from django.db.models import JSONField
from django.db.models import Max
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models import Subquery
from django.db.models import Sum
from django.db.models import UUIDField as DjangoUUIDField
from django.db.models import Value
from django.db.models.expressions import ExpressionList
from django.db.models.expressions import RawSQL
from django.db.models.functions import Cast
from django.db.models.functions import Lower
from django.db.models.indexes import IndexExpression
from django.db.models.query_utils import DeferredAttribute
from django.db.models.sql import Query
from django.dispatch import receiver
from django.utils import timezone
from django.utils.translation import gettext as _
from django_cte import With
from le_utils import proquint
from le_utils.constants import content_kinds
from le_utils.constants import exercises
from le_utils.constants import file_formats
from le_utils.constants import format_presets
from le_utils.constants import languages
from le_utils.constants import roles
from model_utils import FieldTracker
from mptt.models import MPTTModel
from mptt.models import raise_if_unsaved
from mptt.models import TreeForeignKey
from postmark.core import PMMailInactiveRecipientException
from postmark.core import PMMailUnauthorizedException
from rest_framework.authtoken.models import Token

from contentcuration.db.models.expressions import Array
from contentcuration.db.models.functions import ArrayRemove
from contentcuration.db.models.functions import Unnest
from contentcuration.db.models.manager import CustomContentNodeTreeManager
from contentcuration.db.models.manager import CustomManager
from contentcuration.statistics import record_channel_stats
from contentcuration.utils.cache import delete_public_channel_cache_keys
from contentcuration.utils.parser import load_json_string


EDIT_ACCESS = "edit"
VIEW_ACCESS = "view"

DEFAULT_CONTENT_DEFAULTS = {
    'license': None,
    'language': None,
    'author': None,
    'aggregator': None,
    'provider': None,
    'copyright_holder': None,
    'license_description': None,
    'mastery_model': exercises.NUM_CORRECT_IN_A_ROW_5,
    'm_value': 5,
    'n_value': 5,
    'auto_derive_video_thumbnail': True,
    'auto_derive_audio_thumbnail': True,
    'auto_derive_document_thumbnail': True,
    'auto_derive_html5_thumbnail': True,
    'auto_derive_exercise_thumbnail': True,
    'auto_randomize_questions': True,
}
DEFAULT_USER_PREFERENCES = json.dumps(DEFAULT_CONTENT_DEFAULTS, ensure_ascii=False)


class UserManager(BaseUserManager):

    def create_user(self, email, first_name, last_name, password=None):
        if not email:
            raise ValueError('Email address not specified')

        new_user = self.model(
            email=self.normalize_email(email),
        )

        new_user.set_password(password)
        new_user.first_name = first_name
        new_user.last_name = last_name
        new_user.save(using=self._db)
        return new_user

    def create_superuser(self, email, first_name, last_name, password=None):
        new_user = self.create_user(email, first_name, last_name, password=password)
        new_user.is_admin = True
        new_user.save(using=self._db)
        return new_user


class UniqueActiveUserIndex(Index):
    def create_sql(self, model, schema_editor, using='', **kwargs):
        """
        This is a vendored and modified version of the Django create_sql method
        We do this so that we can monkey patch in the unique index statement onto the schema_editor
        while we create the statement for this index, and then revert it to normal.

        We should remove this as soon as Django natively supports UniqueConstraints with Expressions.
        This should hopefully be the case in Django 3.3.
        """
        include = [model._meta.get_field(field_name).column for field_name in self.include]
        condition = self._get_condition_sql(model, schema_editor)
        if self.expressions:
            index_expressions = []
            for expression in self.expressions:
                index_expression = IndexExpression(expression)
                index_expression.set_wrapper_classes(schema_editor.connection)
                index_expressions.append(index_expression)
            expressions = ExpressionList(*index_expressions).resolve_expression(
                Query(model, alias_cols=False),
            )
            fields = None
            col_suffixes = None
        else:
            fields = [
                model._meta.get_field(field_name)
                for field_name, _ in self.fields_orders
            ]
            col_suffixes = [order[1] for order in self.fields_orders]
            expressions = None
        sql = "CREATE UNIQUE INDEX %(name)s ON %(table)s (%(columns)s)%(include)s%(condition)s"
        # Store the normal SQL statement for indexes
        old_create_index_sql = schema_editor.sql_create_index
        # Replace it with our own unique index so that this index actually adds a constraint
        schema_editor.sql_create_index = sql
        # Generate the SQL staetment that we want to return
        return_statement = schema_editor._create_index_sql(
            model, fields=fields, name=self.name, using=using,
            db_tablespace=self.db_tablespace, col_suffixes=col_suffixes,
            opclasses=self.opclasses, condition=condition, include=include,
            expressions=expressions, **kwargs,
        )
        # Reinstate the previous index SQL statement so that we have done no harm
        schema_editor.sql_create_index = old_create_index_sql
        # Return our SQL statement
        return return_statement


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(max_length=100, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    is_admin = models.BooleanField(default=False)
    is_active = models.BooleanField('active', default=False,
                                    help_text='Designates whether this user should be treated as active.')
    is_staff = models.BooleanField('staff status', default=False,
                                   help_text='Designates whether the user can log into this admin site.')
    date_joined = models.DateTimeField('date joined', default=timezone.now)
    clipboard_tree = models.ForeignKey('ContentNode', null=True, blank=True, related_name='user_clipboard', on_delete=models.SET_NULL)
    preferences = models.TextField(default=DEFAULT_USER_PREFERENCES)
    disk_space = models.FloatField(default=524288000, help_text='How many bytes a user can upload')
    disk_space_used = models.FloatField(default=0, help_text='How many bytes a user has uploaded')

    information = JSONField(null=True)
    content_defaults = JSONField(default=dict)
    policies = JSONField(default=dict, null=True)
    feature_flags = JSONField(default=dict, null=True)

    _field_updates = FieldTracker(fields=[
        # Field to watch for changes
        "disk_space",
    ])

    objects = UserManager()
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    def __unicode__(self):
        return self.email

    def delete(self):
        from contentcuration.viewsets.common import SQCount
        # Remove any invitations associated to this account
        self.sent_to.all().delete()

        # Delete channels associated with this user (if user is the only editor)
        user_query = (
            User.objects.filter(editable_channels__id=OuterRef('id'))
                        .values_list('id', flat=True)
                        .distinct()
        )
        self.editable_channels.annotate(num_editors=SQCount(user_query, field="id")).filter(num_editors=1).delete()

        # Delete channel collections associated with this user (if user is the only editor)
        user_query = (
            User.objects.filter(channel_sets__id=OuterRef('id'))
                        .values_list('id', flat=True)
                        .distinct()
        )
        self.channel_sets.annotate(num_editors=SQCount(user_query, field="id")).filter(num_editors=1).delete()

        super(User, self).delete()

    def can_edit(self, channel_id):
        return Channel.filter_edit_queryset(Channel.objects.all(), self).filter(pk=channel_id).exists()

    def check_space(self, size, checksum):
        active_files = self.get_user_active_files()
        if active_files.filter(checksum=checksum).exists():
            return True

        space = self.get_available_space(active_files=active_files)
        if space < size:
            raise PermissionDenied(_("Not enough space. Check your storage under Settings page."))

    def check_channel_space(self, channel):
        active_files = self.get_user_active_files()
        staging_tree_id = channel.staging_tree.tree_id
        channel_files = self.files\
                            .filter(contentnode__tree_id=staging_tree_id)\
                            .values('checksum')\
                            .distinct()\
                            .exclude(checksum__in=active_files.values_list('checksum', flat=True))
        staged_size = float(channel_files.aggregate(used=Sum('file_size'))['used'] or 0)

        if self.get_available_space(active_files=active_files) < (staged_size):
            raise PermissionDenied(_('Out of storage! Request more space under Settings > Storage.'))

    def check_staged_space(self, size, checksum):
        if self.staged_files.filter(checksum=checksum).exists():
            return True
        space = self.get_available_staged_space()
        if space < size:
            raise PermissionDenied(_('Out of storage! Request more space under Settings > Storage.'))

    def get_available_staged_space(self):
        space_used = self.staged_files.values('checksum').distinct().aggregate(size=Sum("file_size"))['size'] or 0
        return float(max(self.disk_space - space_used, 0))

    def get_available_space(self, active_files=None):
        return float(max(self.disk_space - self.get_space_used(active_files=active_files), 0))

    def get_user_active_trees(self):
        return self.editable_channels.exclude(deleted=True)\
            .values_list('main_tree__tree_id', flat=True)

    def get_user_active_files(self):
        active_trees = self.get_user_active_trees()
        return self.files.filter(contentnode__tree_id__in=active_trees)\
            .values('checksum').distinct()

    def get_space_used(self, active_files=None):
        active_files = active_files or self.get_user_active_files()
        files = active_files.aggregate(total_used=Sum('file_size'))
        return float(files['total_used'] or 0)

    def set_space_used(self):
        self.disk_space_used = self.get_space_used()
        self.save()
        return self.disk_space_used

    def get_space_used_by_kind(self):
        active_files = self.get_user_active_files()
        files = active_files.values('preset__kind_id')\
                            .annotate(space=Sum('file_size'))\
                            .order_by()

        kind_dict = {}
        for item in files:
            kind_dict[item['preset__kind_id']] = item['space']
        return kind_dict

    def email_user(self, subject, message, from_email=None, **kwargs):
        try:
            # msg = EmailMultiAlternatives(subject, message, from_email, [self.email])
            # msg.attach_alternative(kwargs["html_message"],"text/html")
            # msg.send()
            send_mail(subject, message, from_email, [self.email], **kwargs)
        except (PMMailInactiveRecipientException, PMMailUnauthorizedException) as e:
            logging.error(str(e))

    def clean(self):
        super(User, self).clean()
        self.email = self.__class__.objects.normalize_email(self.email)

    def get_full_name(self):
        """
        Returns the first_name plus the last_name, with a space in between.
        """
        full_name = '%s %s' % (self.first_name, self.last_name)
        return full_name.strip()

    def get_short_name(self):
        """
        Returns the short name for the user.
        """
        return self.first_name

    def get_token(self):
        token, _ = Token.objects.get_or_create(user=self)
        return token.key

    def save(self, *args, **kwargs):
        from contentcuration.utils.user import calculate_user_storage
        super(User, self).save(*args, **kwargs)

        if 'disk_space' in self._field_updates.changed():
            calculate_user_storage(self.pk)

        changed = False

        if not self.content_defaults:
            self.content_defaults = DEFAULT_CONTENT_DEFAULTS
            changed = True

        if not self.clipboard_tree:
            self.clipboard_tree = ContentNode.objects.create(title=self.email + " clipboard", kind_id=content_kinds.TOPIC)
            self.clipboard_tree.save()
            changed = True

        if changed:
            self.save()

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        indexes = [
            UniqueActiveUserIndex(Lower('email'), condition=Q(is_active=True), name="contentcura_email_d4d492_idx")
        ]

    @classmethod
    def filter_view_queryset(cls, queryset, user):
        if user.is_anonymous:
            return queryset.none()

        if user.is_admin:
            return queryset

        # all shared editors
        all_editable = User.editable_channels.through.objects.all()
        editable = all_editable.filter(
            channel_id__in=all_editable.filter(user_id=user.pk).values_list("channel_id", flat=True)
        )

        # all shared viewers
        all_view_only = User.view_only_channels.through.objects.all()
        view_only = all_view_only.filter(
            channel_id__in=all_view_only.filter(user_id=user.pk).values_list("channel_id", flat=True)
        )

        return queryset.filter(
            Q(pk=user.pk)
            | Q(pk__in=editable.values_list("user_id", flat=True))
            | Q(pk__in=view_only.values_list("user_id", flat=True))
        )

    @classmethod
    def filter_edit_queryset(cls, queryset, user):
        if user.is_anonymous:
            return queryset.none()

        if user.is_admin:
            return queryset

        return queryset.filter(pk=user.pk)

    @classmethod
    def get_for_email(cls, email, **filters):
        """
        Returns the appropriate User record given an email, ordered by:
         - those with is_active=True first, which there should only ever be one
         - otherwise by ID DESC so most recent inactive shoud be returned

        :param email: A string of the user's email
        :param filters: Additional filters to filter the User queryset
        :return: User or None
        """
        return User.objects.filter(email__iexact=email.strip(), **filters)\
            .order_by("-is_active", "-id").first()


class UUIDField(models.CharField):

    def __init__(self, *args, **kwargs):
        kwargs['max_length'] = 32
        super(UUIDField, self).__init__(*args, **kwargs)

    def prepare_value(self, value):
        if isinstance(value, uuid.UUID):
            return value.hex
        return value

    def get_default(self):
        result = super(UUIDField, self).get_default()
        if isinstance(result, uuid.UUID):
            result = result.hex
        return result

    def to_python(self, value):
        if isinstance(value, uuid.UUID):
            return value.hex
        return value


class MPTTTreeIDManager(models.Model):
    """
    Because MPTT uses plain integers for tree IDs and does not use an auto-incrementing field for them,
    the same ID can sometimes be assigned to two trees if two channel create ops happen concurrently.

    As we are using this table only for the ID generation, it does not need any fields.

    We resolve this by creating a dummy table and using its ID as the tree index to take advantage of the db's
    concurrency-friendly way of generating sequential integer IDs. There is a custom migration that ensures
    that the number of records (and thus id) matches the max tree ID number when this table gets added.
    """


def file_on_disk_name(instance, filename):
    """
    Create a name spaced file path from the File obejct's checksum property.
    This path will be used to store the content copy
    :param instance: File (content File model)
    :param filename: str
    :return: str
    """
    return generate_file_on_disk_name(instance.checksum, filename)


def generate_file_on_disk_name(checksum, filename):
    """ Separated from file_on_disk_name to allow for simple way to check if has already exists """
    h = checksum
    basename, ext = os.path.splitext(filename)
    directory = os.path.join(settings.STORAGE_ROOT, h[0], h[1])
    if not os.path.exists(directory):
        os.makedirs(directory)
    return os.path.join(directory, h + ext.lower())


def object_storage_name(instance, filename):
    """
    Create a name spaced file path from the File obejct's checksum property.
    This path will be used to store the content copy

    :param instance: File (content File model)
    :param filename: str
    :return: str
    """

    default_ext = ''
    if instance.file_format_id:
        default_ext = '.{}'.format(instance.file_format_id)

    return generate_object_storage_name(instance.checksum, filename, default_ext)


def generate_object_storage_name(checksum, filename, default_ext=''):
    """ Separated from file_on_disk_name to allow for simple way to check if has already exists """
    h = checksum
    basename, actual_ext = os.path.splitext(filename)
    ext = actual_ext if actual_ext else default_ext

    # Use / instead of os.path.join as Windows makes this \\
    directory = "/".join([settings.STORAGE_ROOT, h[0], h[1]])
    return os.path.join(directory, h + ext.lower())


def generate_storage_url(filename, request=None, *args):
    """
    Generate a storage URL for the given content filename.
    """

    path = generate_object_storage_name(os.path.splitext(filename)[0], filename)

    # There are three scenarios where Studio might be run as:
    #
    # 1. In normal kubernetes, nginx will proxy for us. We'll know we're in kubernetes when the
    # environment variable RUN_MODE=k8s
    #
    # 2. In Docker Compose and bare metal runserver, we'll be running in runserver, and minio
    # will be exposed in port 9000 in the host's localhost network.

    # Note (aron): returning the true storage URL (e.g. https://storage.googleapis.com/storage/a.mp4)
    # isn't too important, because we have CDN in front of our servers, so it should be cached.
    # But change the logic here in case there is a potential for bandwidth and latency improvement.

    # Detect our current state first
    run_mode = os.getenv("RUN_MODE")

    # if we're running inside k8s, then just serve the normal /content/{storage,databases} URL,
    # and let nginx handle proper proxying.
    if run_mode == "k8s":
        url = "/content/{path}".format(
            path=path,
        )

    # if we're in docker-compose or in baremetal, just return the object storage URL as localhost:9000
    elif run_mode == "docker-compose" or run_mode is None:
        # generate the minio storage URL, so we can get the GET parameters that give everyone
        # access even if they don't need to log in
        params = urllib.parse.urlparse(default_storage.url(path)).query
        host = "localhost"
        port = 9000  # hardcoded to the default minio IP address
        url = "http://{host}:{port}/{bucket}/{path}?{params}".format(
            host=host,
            port=port,
            bucket=settings.AWS_S3_BUCKET_NAME,
            path=path,
            params=params,
        )

    return url


class FileOnDiskStorage(FileSystemStorage):
    """
    Overrider FileSystemStorage's default save method to ignore duplicated file.
    """

    def get_available_name(self, name):
        return name

    def _save(self, name, content):
        if self.exists(name):
            # if the file exists, do not call the superclasses _save method
            logging.warn('Content copy "%s" already exists!' % name)
            return name
        return super(FileOnDiskStorage, self)._save(name, content)


class SecretToken(models.Model):
    """Tokens for channels"""
    token = models.CharField(max_length=100, unique=True)
    is_primary = models.BooleanField(default=False)

    @classmethod
    def exists(cls, token):
        """
        Return true when the token string given by string already exists.
        Returns false otherwise.
        """
        return cls.objects.filter(token=token).exists()

    @classmethod
    def generate_new_token(cls):
        """
        Creates a primary secret token for the current channel using a proquint
        string. Creates a secondary token containing the channel id.

        These tokens can be used to refer to the channel to download its content
        database.
        """
        token = proquint.generate()

        # Try 100 times to generate a unique token.
        TRIALS = 100
        for __ in range(TRIALS):
            token = proquint.generate()
            if SecretToken.exists(token):
                continue
            else:
                break
        # after TRIALS attempts and we didn't get a unique token,
        # just raise an error.
        # See https://stackoverflow.com/a/9980160 on what for-else loop does.
        else:
            raise ValueError("Cannot generate new token")

        # We found a unique token! Save it
        return token

    def __str__(self):
        return "{}-{}".format(self.token[:5], self.token[5:])


def get_channel_thumbnail(channel):
    if not isinstance(channel, dict):
        channel = channel.__dict__
    if channel.get("thumbnail_encoding"):
        thumbnail_data = channel.get("thumbnail_encoding")
        if thumbnail_data.get("base64"):
            return thumbnail_data["base64"]

    if channel.get("thumbnail") and 'static' not in channel.get("thumbnail"):
        return generate_storage_url(channel.get("thumbnail"))

    return '/static/img/kolibri_placeholder.png'


CHANNEL_NAME_INDEX_NAME = "channel_name_idx"


# A list of all the FKs from Channel object
# to ContentNode trees
# used for permissions filtering
CHANNEL_TREES = (
    "main_tree",
    "chef_tree",
    "trash_tree",
    "staging_tree",
    "previous_tree",
)


def boolean_val(val):
    return Value(val, output_field=models.BooleanField())


class PermissionCTE(With):
    tree_id_fields = [
        "channel__{}__tree_id".format(tree_name)
        for tree_name in CHANNEL_TREES
    ]

    def __init__(self, model, user_id, **kwargs):
        queryset = model.objects.filter(user_id=user_id)\
            .annotate(
                tree_id=Unnest(ArrayRemove(Array(*self.tree_id_fields), None), output_field=models.IntegerField())
            )
        super(PermissionCTE, self).__init__(queryset=queryset.values("user_id", "channel_id", "tree_id"), **kwargs)

    @classmethod
    def editable_channels(cls, user_id):
        return PermissionCTE(User.editable_channels.through, user_id, name="editable_channels_cte")

    @classmethod
    def view_only_channels(cls, user_id):
        return PermissionCTE(User.view_only_channels.through, user_id, name="view_only_channels_cte")

    def exists(self, *filters):
        return Exists(self.queryset().filter(*filters).values("user_id"))


class Channel(models.Model):
    """ Permissions come from association with organizations """
    id = UUIDField(primary_key=True, default=uuid.uuid4)
    name = models.CharField(max_length=200, blank=True)
    description = models.CharField(max_length=400, blank=True)
    tagline = models.CharField(max_length=150, blank=True, null=True)
    version = models.IntegerField(default=0)
    thumbnail = models.TextField(blank=True, null=True)
    thumbnail_encoding = JSONField(default=dict)
    editors = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='editable_channels',
        verbose_name="editors",
        help_text="Users with edit rights",
        blank=True,
    )
    viewers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='view_only_channels',
        verbose_name="viewers",
        help_text="Users with view only rights",
        blank=True,
    )
    language = models.ForeignKey('Language', null=True, blank=True, related_name='channel_language', on_delete=models.SET_NULL)
    trash_tree = models.ForeignKey('ContentNode', null=True, blank=True, related_name='channel_trash', on_delete=models.SET_NULL)
    clipboard_tree = models.ForeignKey('ContentNode', null=True, blank=True, related_name='channel_clipboard', on_delete=models.SET_NULL)
    main_tree = models.ForeignKey('ContentNode', null=True, blank=True, related_name='channel_main', on_delete=models.SET_NULL)
    staging_tree = models.ForeignKey('ContentNode', null=True, blank=True, related_name='channel_staging', on_delete=models.SET_NULL)
    chef_tree = models.ForeignKey('ContentNode', null=True, blank=True, related_name='channel_chef', on_delete=models.SET_NULL)
    previous_tree = models.ForeignKey('ContentNode', null=True, blank=True, related_name='channel_previous', on_delete=models.SET_NULL)
    bookmarked_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='bookmarked_channels',
        verbose_name="bookmarked by",
    )
    deleted = models.BooleanField(default=False, db_index=True)
    public = models.BooleanField(default=False, db_index=True)
    preferences = models.TextField(default=DEFAULT_USER_PREFERENCES)
    content_defaults = JSONField(default=dict)
    priority = models.IntegerField(default=0, help_text="Order to display public channels")
    last_published = models.DateTimeField(blank=True, null=True)
    secret_tokens = models.ManyToManyField(
        SecretToken,
        related_name='channels',
        verbose_name="secret tokens",
        blank=True,
    )
    source_url = models.CharField(max_length=200, blank=True, null=True)
    demo_server_url = models.CharField(max_length=200, blank=True, null=True)

    # Fields specific to content generated by Ricecooker
    source_id = models.CharField(max_length=200, blank=True, null=True)
    source_domain = models.CharField(max_length=300, blank=True, null=True)
    ricecooker_version = models.CharField(max_length=100, blank=True, null=True)

    # Fields to calculate when channel is published
    published_data = JSONField(default=dict)
    icon_encoding = models.TextField(blank=True, null=True)
    total_resource_count = models.IntegerField(default=0)
    published_kind_count = models.TextField(blank=True, null=True)
    published_size = models.FloatField(default=0)
    included_languages = models.ManyToManyField(
        "Language",
        related_name='channels',
        verbose_name="languages",
        blank=True,
    )

    _field_updates = FieldTracker(fields=[
        # Field to watch for changes
        "description",
        "language_id",
        "thumbnail",
        "name",
        "thumbnail_encoding",
        # watch these fields for changes
        # but exclude them from setting changed
        # on the main tree
        "deleted",
        "public",
        "main_tree_id",
        "version",
    ])

    @classmethod
    def get_editable(cls, user, channel_id):
        return cls.filter_edit_queryset(cls.objects.all(), user).get(id=channel_id)

    @classmethod
    def filter_edit_queryset(cls, queryset, user):
        user_id = not user.is_anonymous and user.id

        # it won't return anything
        if not user_id:
            return queryset.none()

        edit = Exists(User.editable_channels.through.objects.filter(user_id=user_id, channel_id=OuterRef("id")))
        queryset = queryset.annotate(edit=edit)
        if user.is_admin:
            return queryset

        return queryset.filter(edit=True)

    @classmethod
    def filter_view_queryset(cls, queryset, user):
        user_id = not user.is_anonymous and user.id
        user_email = not user.is_anonymous and user.email

        if user_id:
            filters = dict(user_id=user_id, channel_id=OuterRef("id"))
            edit = Exists(User.editable_channels.through.objects.filter(**filters).values("user_id"))
            view = Exists(User.view_only_channels.through.objects.filter(**filters).values("user_id"))
        else:
            edit = boolean_val(False)
            view = boolean_val(False)

        queryset = queryset.annotate(
            edit=edit,
            view=view,
        )

        if user_id and user.is_admin:
            return queryset

        permission_filter = Q()
        if user_id:
            pending_channels = Invitation.objects.filter(email=user_email, revoked=False, declined=False, accepted=False).values_list(
                "channel_id", flat=True
            )
            permission_filter = (
                Q(view=True) | Q(edit=True) | Q(deleted=False, id__in=pending_channels)
            )

        return queryset.filter(permission_filter | Q(deleted=False, public=True))

    @classmethod
    def get_all_channels(cls):
        return cls.objects.select_related('main_tree').prefetch_related('editors', 'viewers').distinct()

    def resource_size_key(self):
        return "{}_resource_size".format(self.pk)

    # Might be good to display resource size, but need to improve query time first

    def get_resource_size(self):
        cached_data = cache.get(self.resource_size_key())
        if cached_data:
            return cached_data
        tree_id = self.main_tree.tree_id
        files = File.objects.select_related('contentnode', 'assessment_item')\
            .filter(contentnode__tree_id=tree_id)\
            .values('checksum', 'file_size')\
            .distinct()\
            .aggregate(resource_size=Sum('file_size'))
        cache.set(self.resource_size_key(), files['resource_size'] or 0, None)
        return files['resource_size'] or 0

    def on_create(self):
        record_channel_stats(self, None)
        if not self.content_defaults:
            self.content_defaults = DEFAULT_CONTENT_DEFAULTS

        if not self.main_tree:
            self.main_tree = ContentNode.objects.create(
                title=self.name,
                kind_id=content_kinds.TOPIC,
                content_id=self.id,
                node_id=self.id,
                original_channel_id=self.id,
                source_channel_id=self.id,
                changed=True,
                complete=True,
            )
            # Ensure that locust or unit tests raise if there are any concurrency issues with tree ids.
            if settings.DEBUG:
                if ContentNode.objects.filter(parent=None, tree_id=self.main_tree.tree_id).count() != 1:
                    raise AssertionError

        if not self.trash_tree:
            self.trash_tree = ContentNode.objects.create(
                title=self.name,
                kind_id=content_kinds.TOPIC,
                content_id=self.id,
                node_id=self.id,
            )

        # if this change affects the public channel list, clear the channel cache
        if self.public:
            delete_public_channel_cache_keys()

    def on_update(self):
        from contentcuration.utils.user import calculate_user_storage
        original_values = self._field_updates.changed()
        record_channel_stats(self, original_values)

        blacklist = set([
            "public",
            "main_tree_id",
            "version",
        ])

        if self.main_tree and original_values and any((True for field in original_values if field not in blacklist)):
            # Changing channel metadata should also mark main_tree as changed
            self.main_tree.changed = True

        # Check if original thumbnail is no longer referenced
        if "thumbnail" in original_values and original_values["thumbnail"] and 'static' not in original_values["thumbnail"]:
            filename, ext = os.path.splitext(original_values["thumbnail"])
            delete_empty_file_reference(filename, ext[1:])

        # Refresh storage for all editors on the channel
        if "deleted" in original_values:
            for editor in self.editors.all():
                calculate_user_storage(editor.pk)

        # Delete db if channel has been deleted and mark as unpublished
        if "deleted" in original_values and not original_values["deleted"]:
            self.pending_editors.all().delete()
            export_db_storage_path = os.path.join(settings.DB_ROOT, "{channel_id}.sqlite3".format(channel_id=self.id))
            if default_storage.exists(export_db_storage_path):
                default_storage.delete(export_db_storage_path)
                if self.main_tree:
                    self.main_tree.published = False

        if self.main_tree and self.main_tree._field_updates.changed():
            self.main_tree.save()

        # if this change affects the public channel list, clear the channel cache
        if "public" in original_values:
            delete_public_channel_cache_keys()

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.on_create()
        else:
            self.on_update()

        super(Channel, self).save(*args, **kwargs)

    def get_thumbnail(self):
        return get_channel_thumbnail(self)

    def has_changes(self):
        return self.main_tree.get_descendants(include_self=True).filter(changed=True).exists()

    def get_date_modified(self):
        return self.main_tree.get_descendants(include_self=True).aggregate(last_modified=Max('modified'))['last_modified']

    def get_resource_count(self):
        return self.main_tree.get_descendants().exclude(kind_id=content_kinds.TOPIC).order_by('content_id').distinct('content_id').count()

    def get_human_token(self):
        return self.secret_tokens.get(is_primary=True)

    def get_channel_id_token(self):
        return self.secret_tokens.get(token=self.id)

    def make_token(self):
        token = self.secret_tokens.create(token=SecretToken.generate_new_token(), is_primary=True)
        self.secret_tokens.get_or_create(token=self.id)
        return token

    def make_public(self, bypass_signals=False):
        """
        Sets the current channel object to be public and viewable by anyone.

        If bypass_signals is True, update the model in such a way that we
        prevent any model signals from running due to the update.

        Returns the same channel object.
        """
        if bypass_signals:
            self.public = True     # set this attribute still, so the object will be updated
            Channel.objects.filter(id=self.id).update(public=True)
            # clear the channel cache
            delete_public_channel_cache_keys()
        else:
            self.public = True
            self.save()

        return self

    @classmethod
    def get_public_channels(cls, defer_nonmain_trees=False):
        """
        Get all public channels.

        If defer_nonmain_trees is True, defer the loading of all
        trees except for the main_tree."""
        if defer_nonmain_trees:
            c = (Channel.objects
                 .filter(public=True)
                 .exclude(deleted=True)
                 .select_related('main_tree')
                 .prefetch_related('editors')
                 .defer('trash_tree', 'clipboard_tree', 'staging_tree', 'chef_tree', 'previous_tree', 'viewers'))
        else:
            c = Channel.objects.filter(public=True).exclude(deleted=True)

        return c

    class Meta:
        verbose_name = "Channel"
        verbose_name_plural = "Channels"

        indexes = [
            models.Index(fields=["name"], name=CHANNEL_NAME_INDEX_NAME),
        ]
        index_together = [
            ["deleted", "public"]
        ]


class ChannelSet(models.Model):
    # NOTE: this is referred to as "channel collections" on the front-end, but we need to call it
    # something else as there is already a ChannelCollection model on the front-end
    id = UUIDField(primary_key=True, default=uuid.uuid4)
    name = models.CharField(max_length=200, blank=True)
    description = models.CharField(max_length=400, blank=True)
    public = models.BooleanField(default=False, db_index=True)
    editors = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='channel_sets',
        verbose_name="editors",
        help_text="Users with edit rights",
        blank=True,
    )
    secret_token = models.ForeignKey('SecretToken', null=True, blank=True, related_name='channel_sets', on_delete=models.SET_NULL)

    @classmethod
    def filter_edit_queryset(cls, queryset, user):
        if user.is_anonymous:
            return queryset.none()
        user_id = not user.is_anonymous and user.id
        edit = Exists(User.channel_sets.through.objects.filter(user_id=user_id, channelset_id=OuterRef("id")))
        queryset = queryset.annotate(edit=edit)
        if user.is_admin:
            return queryset

        return queryset.filter(edit=True)

    @classmethod
    def filter_view_queryset(cls, queryset, user):
        return cls.filter_edit_queryset(queryset, user)

    def get_channels(self):
        if self.secret_token:
            return self.secret_token.channels.filter(deleted=False)

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.on_create()

        super(ChannelSet, self).save()

    def on_create(self):
        if not self.secret_token:
            self.secret_token = SecretToken.objects.create(token=SecretToken.generate_new_token())

    def delete(self, *args, **kwargs):
        super(ChannelSet, self).delete(*args, **kwargs)

        if self.secret_token:
            self.secret_token.delete()


class ContentTag(models.Model):
    id = UUIDField(primary_key=True, default=uuid.uuid4)
    tag_name = models.CharField(max_length=50)
    channel = models.ForeignKey('Channel', related_name='tags', blank=True, null=True, db_index=True, on_delete=models.SET_NULL)
    objects = CustomManager()

    def __str__(self):
        return self.tag_name

    class Meta:
        unique_together = ['tag_name', 'channel']


def delegate_manager(method):
    """
    Delegate method calls to base manager, if exists.
    """

    @functools.wraps(method)
    def wrapped(self, *args, **kwargs):
        if self._base_manager:
            return getattr(self._base_manager, method.__name__)(*args, **kwargs)
        return method(self, *args, **kwargs)

    return wrapped


class License(models.Model):
    """
    Normalize the license of ContentNode model
    """
    license_name = models.CharField(max_length=50)
    license_url = models.URLField(blank=True)
    license_description = models.TextField(blank=True)
    copyright_holder_required = models.BooleanField(default=True)
    is_custom = models.BooleanField(default=False)
    exists = models.BooleanField(
        default=False,
        verbose_name="license exists",
        help_text="Tells whether or not a content item is licensed to share",
    )

    @classmethod
    def validate_name(cls, name):
        if cls.objects.filter(license_name=name).count() == 0:
            raise ValidationError('License `{}` does not exist'.format(name))

    def __str__(self):
        return self.license_name


NODE_ID_INDEX_NAME = "node_id_idx"
NODE_MODIFIED_INDEX_NAME = "node_modified_idx"
NODE_MODIFIED_DESC_INDEX_NAME = "node_modified_desc_idx"


class ContentNode(MPTTModel, models.Model):
    """
    By default, all nodes have a title and can be used as a topic.
    """
    # Random id used internally on Studio (See `node_id` for id used in Kolibri)
    id = UUIDField(primary_key=True, default=uuid.uuid4)

    # the content_id is used for tracking a user's interaction with a piece of
    # content, in the face of possibly many copies of that content. When a user
    # interacts with a piece of content, all substantially similar pieces of
    # content should be marked as such as well. We track these "substantially
    # similar" types of content by having them have the same content_id.
    content_id = UUIDField(primary_key=False, default=uuid.uuid4, editable=False, db_index=True)
    # Note this field is indexed, but we are using the Index API to give it an explicit name, see the model Meta
    node_id = UUIDField(primary_key=False, default=uuid.uuid4, editable=False)

    # TODO: disallow nulls once existing models have been set
    original_channel_id = UUIDField(primary_key=False, editable=False, null=True,
                                    db_index=True)  # Original channel copied from
    source_channel_id = UUIDField(primary_key=False, editable=False, null=True)  # Immediate channel copied from
    # Original node_id of node copied from (TODO: original_node_id clashes with original_node field - temporary)
    original_source_node_id = UUIDField(primary_key=False, editable=False, null=True,
                                        db_index=True)
    source_node_id = UUIDField(primary_key=False, editable=False, null=True)  # Immediate node_id of node copied from

    # Fields specific to content generated by Ricecooker
    source_id = models.CharField(max_length=200, blank=True, null=True)
    source_domain = models.CharField(max_length=300, blank=True, null=True)

    title = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    kind = models.ForeignKey('ContentKind', related_name='contentnodes', db_index=True, null=True, blank=True, on_delete=models.SET_NULL)
    license = models.ForeignKey('License', null=True, blank=True, on_delete=models.SET_NULL)
    license_description = models.CharField(max_length=400, null=True, blank=True)
    prerequisite = models.ManyToManyField('self', related_name='is_prerequisite_of',
                                          through='PrerequisiteContentRelationship', symmetrical=False, blank=True)
    is_related = models.ManyToManyField('self', related_name='relate_to', through='RelatedContentRelationship',
                                        symmetrical=False, blank=True)
    language = models.ForeignKey('Language', null=True, blank=True, related_name='content_language', on_delete=models.SET_NULL)
    parent = TreeForeignKey('self', null=True, blank=True, related_name='children', db_index=True, on_delete=models.CASCADE)
    tags = models.ManyToManyField(ContentTag, symmetrical=False, related_name='tagged_content', blank=True)
    # No longer used
    sort_order = models.FloatField(max_length=50, default=1, verbose_name="sort order",
                                   help_text="Ascending, lowest number shown first")
    copyright_holder = models.CharField(max_length=200, null=True, blank=True, default="",
                                        help_text="Organization of person who holds the essential rights")
    # legacy field...
    original_node = TreeForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='duplicates')
    cloned_source = TreeForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='clones')

    thumbnail_encoding = models.TextField(blank=True, null=True)

    created = models.DateTimeField(default=timezone.now, verbose_name="created")
    modified = models.DateTimeField(auto_now=True, verbose_name="modified")
    published = models.BooleanField(default=False)
    publishing = models.BooleanField(default=False)
    complete = models.BooleanField(null=True)

    changed = models.BooleanField(default=True)
    """
        Extra fields for exercises:
        - type: mastery model to use to determine completion
        - m: m value for M out of N mastery criteria
        - n: n value for M out of N mastery criteria
    """
    extra_fields = JSONField(default=dict, blank=True, null=True)
    author = models.CharField(max_length=200, blank=True, default="", help_text="Who created this content?",
                              null=True)
    aggregator = models.CharField(max_length=200, blank=True, default="", help_text="Who gathered this content together?",
                                  null=True)
    provider = models.CharField(max_length=200, blank=True, default="", help_text="Who distributed this content?",
                                null=True)

    role_visibility = models.CharField(max_length=50, choices=roles.choices, default=roles.LEARNER)
    freeze_authoring_data = models.BooleanField(default=False)

    objects = CustomContentNodeTreeManager()

    # Track all updates and ignore a blacklist of attributes
    # when we check for changes
    _field_updates = FieldTracker()

    _permission_filter = Q(tree_id=OuterRef("tree_id"))

    @classmethod
    def _annotate_channel_id(cls, queryset):
        # Annotate channel id
        return queryset.annotate(
            channel_id=Subquery(
                Channel.objects.filter(
                    main_tree__tree_id=OuterRef("tree_id")
                ).values_list("id", flat=True)[:1]
            )
        )

    @classmethod
    def _orphan_tree_id_subquery(cls):
        # For some reason this now requires an explicit type cast
        # or it gets interpreted as a varchar
        return Cast(cls.objects.filter(
            pk=settings.ORPHANAGE_ROOT_ID
        ).values_list("tree_id", flat=True)[:1], output_field=IntegerField())

    @classmethod
    def filter_edit_queryset(cls, queryset, user):
        user_id = not user.is_anonymous and user.id

        queryset = queryset.exclude(pk=settings.ORPHANAGE_ROOT_ID)

        if not user_id:
            return queryset.none()

        edit_cte = PermissionCTE.editable_channels(user_id)

        queryset = queryset.with_cte(edit_cte).annotate(
            edit=edit_cte.exists(cls._permission_filter),
        )

        if user.is_admin:
            return queryset

        return queryset.filter(Q(edit=True) | Q(tree_id=cls._orphan_tree_id_subquery()))

    @classmethod
    def filter_view_queryset(cls, queryset, user):
        user_id = not user.is_anonymous and user.id

        queryset = queryset.annotate(
            public=Exists(
                Channel.objects.filter(
                    public=True, main_tree__tree_id=OuterRef("tree_id")
                ).values("pk")
            ),
        ).exclude(pk=settings.ORPHANAGE_ROOT_ID)

        if not user_id:
            return queryset.annotate(edit=boolean_val(False), view=boolean_val(False)).filter(public=True)

        edit_cte = PermissionCTE.editable_channels(user_id)
        view_cte = PermissionCTE.view_only_channels(user_id)

        queryset = queryset.with_cte(edit_cte).with_cte(view_cte).annotate(
            edit=edit_cte.exists(cls._permission_filter),
            view=view_cte.exists(cls._permission_filter),
        )

        if user.is_admin:
            return queryset

        return queryset.filter(
            Q(view=True)
            | Q(edit=True)
            | Q(public=True)
            | Q(tree_id=cls._orphan_tree_id_subquery())
        )

    @raise_if_unsaved
    def get_root(self):
        # Only topics can be root nodes
        if self.is_root_node() and self.kind_id != content_kinds.TOPIC:
            return self
        return super(ContentNode, self).get_root()

    @raise_if_unsaved
    def get_root_id(self):
        # Only topics can be root nodes
        if self.is_root_node() and self.kind_id != content_kinds.TOPIC:
            return self

        return ContentNode.objects.values_list('pk', flat=True).get(
            tree_id=self._mpttfield('tree_id'),
            parent=None,
        )

    def get_tree_data(self, levels=float('inf')):
        """
        Returns `levels`-deep tree information starting at current node.
        Args:
          levels (int): depth of tree hierarchy to return
        Returns:
          tree (dict): starting with self, with children list containing either
                       the just the children's `node_id`s or full recusive tree.
        """
        if self.kind_id == content_kinds.TOPIC:
            node_data = {
                "title": self.title,
                "kind": self.kind_id,
                "node_id": self.node_id,
                "studio_id": self.id,
            }
            children = self.children.all()
            if levels > 0:
                node_data["children"] = [c.get_tree_data(levels=levels - 1) for c in children]
            return node_data
        if self.kind_id == content_kinds.EXERCISE:
            return {
                "title": self.title,
                "kind": self.kind_id,
                "count": self.assessment_items.count(),
                "node_id": self.node_id,
                "studio_id": self.id,
            }
        return {
            "title": self.title,
            "kind": self.kind_id,
            "file_size": self.files.values('file_size').aggregate(size=Sum('file_size'))['size'],
            "node_id": self.node_id,
            "studio_id": self.id,
        }

    def get_original_node(self):
        original_node = self.original_node or self
        if self.original_channel_id and self.original_source_node_id:
            original_tree_id = Channel.objects.select_related("main_tree").get(pk=self.original_channel_id).main_tree.tree_id
            original_node = ContentNode.objects.filter(tree_id=original_tree_id, node_id=self.original_source_node_id).first() or \
                ContentNode.objects.filter(tree_id=original_tree_id, content_id=self.content_id).first() or self
        return original_node

    def get_associated_presets(self):
        key = "associated_presets_{}".format(self.kind_id)
        cached_data = cache.get(key)
        if cached_data:
            return cached_data
        presets = list(FormatPreset.objects.filter(kind=self.kind).values())
        cache.set(key, presets, None)
        return presets

    def get_prerequisites(self):
        prerequisite_mapping = {}
        prerequisites = self.prerequisite.all()
        prereqlist = list(prerequisites)
        for prereq in prerequisites:
            prlist, prereqmapping = prereq.get_prerequisites()
            prerequisite_mapping.update({prereq.pk: prereqmapping})
            prereqlist.extend(prlist)
        return prereqlist, prerequisite_mapping

    def get_postrequisites(self):
        postrequisite_mapping = {}
        postrequisites = self.is_prerequisite_of.all()
        postreqlist = list(postrequisites)
        for postreq in postrequisites:
            prlist, postreqmapping = postreq.get_postrequisites()
            postrequisite_mapping.update({postreq.pk: postreqmapping})
            postreqlist.extend(prlist)
        return postreqlist, postrequisite_mapping

    def get_channel_id(self):
        if hasattr(self, "channel_id"):
            return self.channel_id
        channel = self.get_channel()
        if channel:
            return channel.id
        return None

    def get_channel(self):
        try:
            root = self.get_root()
            if not root:
                return None
            return Channel.objects.filter(Q(main_tree=root) | Q(chef_tree=root) | Q(trash_tree=root) | Q(staging_tree=root) | Q(previous_tree=root)).first()
        except (ObjectDoesNotExist, MultipleObjectsReturned, AttributeError):
            return None

    def get_thumbnail(self):
        # Problems with json.loads, so use ast.literal_eval to get dict
        if self.thumbnail_encoding:
            thumbnail_data = load_json_string(self.thumbnail_encoding)
            if type(thumbnail_data) is dict and thumbnail_data.get("base64"):
                return thumbnail_data["base64"]

        thumbnail = self.files.filter(preset__thumbnail=True).first()
        if thumbnail:
            return generate_storage_url(str(thumbnail))

        return ""

    @classmethod
    def get_nodes_with_title(cls, title, limit_to_children_of=None):
        """
        Returns all ContentNodes with a given title. If limit_to_children_of
        is passed in with an id, only look at all the children of the node with that id.
        """
        if limit_to_children_of:
            root = cls.objects.get(id=limit_to_children_of)
            return root.get_descendants().filter(title=title)
        return cls.objects.filter(title=title)

    def get_details(self, channel_id=None):
        """
        Returns information about the node and its children, including total size, languages, files, etc.

        :return: A dictionary with detailed statistics and information about the node.
        """
        from contentcuration.viewsets.common import SQArrayAgg
        from contentcuration.viewsets.common import SQCount
        from contentcuration.viewsets.common import SQRelatedArrayAgg
        from contentcuration.viewsets.common import SQSum

        node = ContentNode.objects.filter(pk=self.id).order_by()

        descendants = (
            self.get_descendants()
            .prefetch_related("children", "files", "tags")
            .select_related("license", "language")
            .values("id")
        )

        if channel_id:
            channel = Channel.objects.filter(id=channel_id)[0]
        else:
            channel = self.get_channel()

        if not descendants.exists():
            data = {
                "last_update": pytz.utc.localize(datetime.now()).strftime(
                    settings.DATE_TIME_FORMAT
                ),
                "created": self.created.strftime(settings.DATE_TIME_FORMAT),
                "resource_count": 0,
                "resource_size": 0,
                "includes": {"coach_content": 0, "exercises": 0},
                "kind_count": [],
                "languages": "",
                "accessible_languages": "",
                "licenses": "",
                "tags": [],
                "copyright_holders": "",
                "authors": "",
                "aggregators": "",
                "providers": "",
                "sample_pathway": [],
                "original_channels": [],
                "sample_nodes": [],
            }

            # Set cache with latest data
            cache.set("details_{}".format(self.node_id), json.dumps(data), None)
            return data

        # Get resources
        resources = descendants.exclude(kind=content_kinds.TOPIC).order_by()
        nodes = With(
            File.objects.filter(contentnode_id__in=Subquery(resources.values("id")))
            .values("checksum", "file_size")
            .order_by(),
            name="nodes",
        )
        file_query = (
            nodes.queryset().with_cte(nodes).values("checksum", "file_size").distinct()
        )
        l_nodes = With(
            File.objects.filter(contentnode_id__in=Subquery(resources.values("id")))
            .values("language_id", "preset_id")
            .order_by(),
            name="l_nodes",
        )
        accessible_languages_query = (
            l_nodes.queryset()
            .filter(preset_id=format_presets.VIDEO_SUBTITLE)
            .with_cte(l_nodes)
            .values("language__native_name")
            .distinct()
        )

        tags_query = str(
            ContentTag.objects.filter(
                tagged_content__pk__in=descendants.values_list("pk", flat=True)
            )
            .values("tag_name")
            .annotate(count=Count("tag_name"))
            .query
        ).replace("topic", "'topic'")
        kind_count_query = str(
            resources.values("kind_id").annotate(count=Count("kind_id")).query
        ).replace("topic", "'topic'")

        node = node.annotate(
            resource_count=SQCount(resources, field="id"),
            resource_size=SQSum(file_query, field="file_size"),
            copyright_holders=SQArrayAgg(
                resources.distinct("copyright_holder").order_by("copyright_holder"),
                field="copyright_holder",
            ),
            authors=SQArrayAgg(
                resources.distinct("author").order_by("author"), field="author"
            ),
            aggregators=SQArrayAgg(
                resources.distinct("aggregator").order_by("aggregator"),
                field="aggregator",
            ),
            providers=SQArrayAgg(
                resources.distinct("provider").order_by("provider"), field="provider"
            ),
            languages=SQRelatedArrayAgg(
                descendants.exclude(language=None)
                .distinct("language__native_name")
                .order_by(),
                field="language__native_name",
                fieldname="native_name",
            ),
            accessible_languages=SQRelatedArrayAgg(
                accessible_languages_query,
                field="language__native_name",
                fieldname="native_name",
            ),
            licenses=SQRelatedArrayAgg(
                resources.exclude(license=None)
                .distinct("license__license_name")
                .order_by("license__license_name"),
                field="license__license_name",
                fieldname="license_name",
            ),
            kind_count=RawSQL(
                "SELECT json_agg(row_to_json (x)) FROM ({}) as x".format(
                    kind_count_query
                ),
                (),
            ),
            tags_list=RawSQL(
                "SELECT json_agg(row_to_json (x)) FROM ({}) as x".format(tags_query), ()
            ),
            coach_content=SQCount(
                resources.filter(role_visibility=roles.COACH), field="id"
            ),
            exercises=SQCount(
                resources.filter(kind_id=content_kinds.EXERCISE), field="id"
            ),
        )

        # Get sample pathway by getting longest path
        # Using resources.aggregate adds a lot of time, use values that have already been fetched
        max_level = max(
            resources.values_list("level", flat=True).order_by().distinct() or [0]
        )
        m_nodes = With(
            resources.values("id", "level", "tree_id", "lft").order_by(),
            name="m_nodes",
        )
        deepest_node_record = (
            m_nodes.queryset()
            .with_cte(m_nodes)
            .filter(level=max_level)
            .values("id")
            .order_by("tree_id", "lft")
            .first()
        )
        if deepest_node_record:
            deepest_node = ContentNode.objects.get(pk=deepest_node_record["id"])
        pathway = (
            list(
                deepest_node.get_ancestors()
                .order_by()
                .exclude(parent=None)
                .values("title", "node_id", "kind_id")
                .order_by()
            )
            if deepest_node_record
            else []
        )
        sample_nodes = (
            [
                {
                    "node_id": n.node_id,
                    "title": n.title,
                    "description": n.description,
                    "thumbnail": n.get_thumbnail(),
                    "kind": n.kind_id,
                }
                for n in deepest_node.get_siblings(include_self=True)[0:4]
            ]
            if deepest_node_record
            else []
        )

        # Get list of channels nodes were originally imported from (omitting the current channel)
        channel_id = channel and channel.id
        originals = (
            resources.values("original_channel_id")
            .annotate(count=Count("original_channel_id"))
            .order_by("original_channel_id")
        )
        originals = {c["original_channel_id"]: c["count"] for c in originals}
        original_channels = (
            Channel.objects.exclude(pk=channel_id)
            .filter(pk__in=originals.keys(), deleted=False)
            .order_by()
        )
        original_channels = [
            {
                "id": c.id,
                "name": "{}{}".format(
                    c.name, _(" (Original)") if channel_id == c.id else ""
                ),
                "thumbnail": c.get_thumbnail(),
                "count": originals[c.id],
            }
            for c in original_channels
        ]

        node = (
            node.order_by()
            .values(
                "id",
                "resource_count",
                "resource_size",
                "copyright_holders",
                "authors",
                "aggregators",
                "providers",
                "languages",
                "accessible_languages",
                "coach_content",
                "licenses",
                "tags_list",
                "kind_count",
                "exercises",
            )
            .first()
        )
        for_educators = {
            "coach_content": node["coach_content"],
            "exercises": node["exercises"],
        }
        # Serialize data
        data = {
            "last_update": pytz.utc.localize(datetime.now()).strftime(
                settings.DATE_TIME_FORMAT
            ),
            "created": self.created.strftime(settings.DATE_TIME_FORMAT),
            "resource_count": node.get("resource_count", 0),
            "resource_size": node.get("resource_size", 0),
            "includes": for_educators,
            "kind_count": node.get("kind_count", []),
            "languages": node.get("languages", ""),
            "accessible_languages": node.get("accessible_languages", ""),
            "licenses": node.get("licenses", ""),
            "tags": node.get("tags_list", []),
            "copyright_holders": node["copyright_holders"],
            "authors": node["authors"],
            "aggregators": node["aggregators"],
            "providers": node["providers"],
            "sample_pathway": pathway,
            "original_channels": original_channels,
            "sample_nodes": sample_nodes,
        }

        # Set cache with latest data
        cache.set("details_{}".format(self.node_id), json.dumps(data), None)
        return data

    def has_changes(self):
        mptt_opts = self._mptt_meta
        # Ignore fields that are used for dirty tracking, and also mptt fields, as changes to these are tracked in mptt manager methods.
        blacklist = set([
            'changed',
            'modified',
            'publishing',
            mptt_opts.tree_id_attr,
            mptt_opts.left_attr,
            mptt_opts.right_attr,
            mptt_opts.level_attr,
        ])
        original_values = self._field_updates.changed()
        return any((True for field in original_values if field not in blacklist))

    def recalculate_editors_storage(self):
        from contentcuration.utils.user import calculate_user_storage
        for editor in self.files.values_list('uploaded_by_id', flat=True).distinct():
            calculate_user_storage(editor)

    def on_create(self):
        self.changed = True
        self.recalculate_editors_storage()

    def on_update(self):
        self.changed = self.changed or self.has_changes()

    def move_to(self, target, *args, **kwargs):
        parent_was_trashtree = self.parent.channel_trash.exists()
        super(ContentNode, self).move_to(target, *args, **kwargs)

        # Recalculate storage if node was moved to or from the trash tree
        if target.channel_trash.exists() or parent_was_trashtree:
            self.recalculate_editors_storage()

    def save(self, skip_lock=False, *args, **kwargs):
        if self._state.adding:
            self.on_create()
        else:
            self.on_update()

        # Logic borrowed from mptt - do a simple check to see if we have changed
        # the parent of the node. We use the mptt specific cached fields here
        # because these get updated by the mptt move methods, and so will be up to
        # date, meaning we can avoid locking the DB twice when the fields have already
        # been updated in the database.

        # If most moves are being done independently of just changing the parent
        # and then calling a save, locking within the save method itself should rarely
        # be triggered - meaning updates to contentnode metadata should only rarely
        # trigger a write lock on mptt fields.

        old_parent_id = self._field_updates.changed().get("parent_id")
        if self._state.adding and (self.parent_id or self.parent):
            same_order = False
        elif old_parent_id is DeferredAttribute:
            same_order = True
        else:
            same_order = old_parent_id == self.parent_id

        if not same_order:
            changed_ids = list(filter(lambda x: x is not None, set([old_parent_id, self.parent_id])))
        else:
            changed_ids = []

        if not same_order and not skip_lock:
            # Lock the mptt fields for the trees of the old and new parent
            with ContentNode.objects.lock_mptt(*ContentNode.objects
                                               .filter(id__in=[pid for pid in [old_parent_id, self.parent_id] if pid])
                                               .values_list('tree_id', flat=True).distinct()):
                super(ContentNode, self).save(*args, **kwargs)
                # Always write to the database for the parent change updates, as we have
                # no persistent object references for the original and new parent to modify
                if changed_ids:
                    ContentNode.objects.filter(id__in=changed_ids).update(changed=True)
        else:
            super(ContentNode, self).save(*args, **kwargs)
            # Always write to the database for the parent change updates, as we have
            # no persistent object references for the original and new parent to modify
            if changed_ids:
                ContentNode.objects.filter(id__in=changed_ids).update(changed=True)

    # Copied from MPTT
    save.alters_data = True

    def delete(self, *args, **kwargs):
        parent = self.parent or self._field_updates.changed().get('parent')
        if parent:
            parent.changed = True
            parent.save()

        self.recalculate_editors_storage()

        # Lock the mptt fields for the tree of this node
        with ContentNode.objects.lock_mptt(self.tree_id):
            return super(ContentNode, self).delete(*args, **kwargs)

    # Copied from MPTT
    delete.alters_data = True

    def copy_to(
        self,
        target=None,
        position="last-child",
        pk=None,
        mods=None,
        excluded_descendants=None,
        can_edit_source_channel=None,
        batch_size=None,
        progress_tracker=None
    ):
        return self._tree_manager.copy_node(self, target, position, pk, mods, excluded_descendants, can_edit_source_channel, batch_size, progress_tracker)[0]

    def copy(self):
        return self.copy_to()

    class Meta:
        verbose_name = "Topic"
        verbose_name_plural = "Topics"
        # Do not allow two nodes with the same name on the same level
        # unique_together = ('parent', 'title')
        indexes = [
            models.Index(fields=["node_id"], name=NODE_ID_INDEX_NAME),
            models.Index(fields=["-modified"], name=NODE_MODIFIED_DESC_INDEX_NAME),
        ]


class ContentKind(models.Model):
    kind = models.CharField(primary_key=True, max_length=200, choices=content_kinds.choices)

    def __str__(self):
        return self.kind


class FileFormat(models.Model):
    extension = models.CharField(primary_key=True, max_length=40, choices=file_formats.choices)
    mimetype = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return self.extension


class FormatPreset(models.Model):
    id = models.CharField(primary_key=True, max_length=150, choices=format_presets.choices)
    readable_name = models.CharField(max_length=400)
    multi_language = models.BooleanField(default=False)
    supplementary = models.BooleanField(default=False)
    thumbnail = models.BooleanField(default=False)
    subtitle = models.BooleanField(default=False)
    display = models.BooleanField(default=True)  # Render on client side
    order = models.IntegerField(default=0)
    kind = models.ForeignKey(ContentKind, related_name='format_presets', null=True, on_delete=models.SET_NULL)
    allowed_formats = models.ManyToManyField(FileFormat, blank=True)

    def __str__(self):
        return self.id

    @classmethod
    def guess_format_preset(cls, filename):
        """
        Guess the format preset of a filename based on its extension.

        Return None if format is unknown.
        """

        _, ext = os.path.splitext(filename)
        ext = ext.lstrip(".")
        f = FormatPreset.objects.filter(
            allowed_formats__extension=ext,
            display=True
        )
        return f.first()

    @classmethod
    def get_preset(cls, preset_name):
        """
        Get the FormatPreset object with that exact name.

        Returns None if that format preset is not found.
        """
        try:
            return FormatPreset.objects.get(id=preset_name)
        except FormatPreset.DoesNotExist:
            return None


class Language(models.Model):
    id = models.CharField(max_length=14, primary_key=True)
    lang_code = models.CharField(max_length=3, db_index=True)
    lang_subcode = models.CharField(max_length=10, db_index=True, blank=True, null=True)
    readable_name = models.CharField(max_length=100, blank=True)
    native_name = models.CharField(max_length=100, blank=True)
    lang_direction = models.CharField(max_length=3, choices=languages.LANGUAGE_DIRECTIONS, default=languages.LANGUAGE_DIRECTIONS[0][0])

    def ietf_name(self):
        return "{code}-{subcode}".format(code=self.lang_code,
                                         subcode=self.lang_subcode) if self.lang_subcode else self.lang_code

    def __str__(self):
        return self.ietf_name()


ASSESSMENT_ID_INDEX_NAME = "assessment_id_idx"


class AssessmentItem(models.Model):
    type = models.CharField(max_length=50, default="multiplechoice")
    question = models.TextField(blank=True)
    hints = models.TextField(default="[]")
    answers = models.TextField(default="[]")
    order = models.IntegerField(default=1)
    contentnode = models.ForeignKey('ContentNode', related_name="assessment_items", blank=True, null=True,
                                    db_index=True, on_delete=models.CASCADE)
    # Note this field is indexed, but we are using the Index API to give it an explicit name, see the model Meta
    assessment_id = UUIDField(primary_key=False, default=uuid.uuid4, editable=False)
    raw_data = models.TextField(blank=True)
    source_url = models.CharField(max_length=400, blank=True, null=True)
    randomize = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False)

    objects = CustomManager()
    # Track all updates
    _field_updates = FieldTracker()

    def has_changes(self):
        return bool(self._field_updates.changed())

    class Meta:
        indexes = [
            models.Index(fields=["assessment_id"], name=ASSESSMENT_ID_INDEX_NAME),
        ]

        unique_together = ['contentnode', 'assessment_id']

    _permission_filter = Q(tree_id=OuterRef("contentnode__tree_id"))

    @classmethod
    def filter_edit_queryset(cls, queryset, user):
        user_id = not user.is_anonymous and user.id

        if not user_id:
            return queryset.none()

        edit_cte = PermissionCTE.editable_channels(user_id)

        queryset = queryset.with_cte(edit_cte).annotate(
            edit=edit_cte.exists(cls._permission_filter),
        )

        if user.is_admin:
            return queryset

        return queryset.filter(edit=True)

    @classmethod
    def filter_view_queryset(cls, queryset, user):
        user_id = not user.is_anonymous and user.id

        queryset = queryset.annotate(
            public=Exists(
                Channel.objects.filter(
                    public=True, main_tree__tree_id=OuterRef("contentnode__tree_id")
                ).values("pk")
            ),
        )

        if not user_id:
            return queryset.annotate(edit=boolean_val(False), view=boolean_val(False)).filter(public=True)

        edit_cte = PermissionCTE.editable_channels(user_id)
        view_cte = PermissionCTE.view_only_channels(user_id)

        queryset = queryset.with_cte(edit_cte).with_cte(view_cte).annotate(
            edit=edit_cte.exists(cls._permission_filter),
            view=view_cte.exists(cls._permission_filter),
        )

        if user.is_admin:
            return queryset

        return queryset.filter(Q(view=True) | Q(edit=True) | Q(public=True))


class SlideshowSlide(models.Model):
    contentnode = models.ForeignKey('ContentNode', related_name="slideshow_slides", blank=True, null=True,
                                    db_index=True, on_delete=models.CASCADE)
    sort_order = models.FloatField(default=1.0)
    metadata = JSONField(default=dict)


class StagedFile(models.Model):
    """
    Keeps track of files uploaded through Ricecooker to avoid user going over disk quota limit
    """
    checksum = models.CharField(max_length=400, blank=True, db_index=True)
    file_size = models.IntegerField(blank=True, null=True)
    uploaded_by = models.ForeignKey(User, related_name='staged_files', blank=True, null=True, on_delete=models.CASCADE)


FILE_DISTINCT_INDEX_NAME = "file_checksum_file_size_idx"
FILE_MODIFIED_DESC_INDEX_NAME = "file_modified_desc_idx"


class File(models.Model):
    """
    The bottom layer of the contentDB schema, defines the basic building brick for content.
    Things it can represent are, for example, mp4, avi, mov, html, css, jpeg, pdf, mp3...
    """
    id = UUIDField(primary_key=True, default=uuid.uuid4)
    checksum = models.CharField(max_length=400, blank=True, db_index=True)
    file_size = models.IntegerField(blank=True, null=True)
    file_on_disk = models.FileField(upload_to=object_storage_name, storage=default_storage, max_length=500,
                                    blank=True)
    contentnode = models.ForeignKey(ContentNode, related_name='files', blank=True, null=True, db_index=True, on_delete=models.CASCADE)
    assessment_item = models.ForeignKey(AssessmentItem, related_name='files', blank=True, null=True, db_index=True, on_delete=models.CASCADE)
    slideshow_slide = models.ForeignKey(SlideshowSlide, related_name='files', blank=True, null=True, db_index=True, on_delete=models.CASCADE)
    file_format = models.ForeignKey(FileFormat, related_name='files', blank=True, null=True, db_index=True, on_delete=models.SET_NULL)
    preset = models.ForeignKey(FormatPreset, related_name='files', blank=True, null=True, db_index=True, on_delete=models.SET_NULL)
    language = models.ForeignKey(Language, related_name='files', blank=True, null=True, on_delete=models.SET_NULL)
    original_filename = models.CharField(max_length=255, blank=True)
    source_url = models.CharField(max_length=400, blank=True, null=True)
    uploaded_by = models.ForeignKey(User, related_name='files', blank=True, null=True, on_delete=models.SET_NULL)

    modified = models.DateTimeField(auto_now=True, verbose_name="modified", null=True)

    objects = CustomManager()

    _permission_filter = Q(tree_id=OuterRef("contentnode__tree_id")) | Q(tree_id=OuterRef("assessment_item__contentnode__tree_id"))

    @classmethod
    def filter_edit_queryset(cls, queryset, user):
        user_id = not user.is_anonymous and user.id

        if not user_id:
            return queryset.none()

        cte = PermissionCTE.editable_channels(user_id)
        queryset = queryset.with_cte(cte).annotate(edit=cte.exists(cls._permission_filter))

        if user.is_admin:
            return queryset

        return queryset.filter(
            Q(edit=True) | Q(uploaded_by=user, contentnode__isnull=True, assessment_item__isnull=True)
        )

    @classmethod
    def filter_view_queryset(cls, queryset, user):
        user_id = not user.is_anonymous and user.id

        queryset = queryset.annotate(
            public=Exists(
                Channel.objects.filter(public=True).filter(
                    Q(main_tree__tree_id=OuterRef("contentnode__tree_id"))
                    | Q(main_tree__tree_id=OuterRef("assessment_item__contentnode__tree_id"))
                ).values("pk")
            ),
        )

        if not user_id:
            return queryset.annotate(edit=boolean_val(False), view=boolean_val(False)).filter(public=True)

        edit_cte = PermissionCTE.editable_channels(user_id)
        view_cte = PermissionCTE.view_only_channels(user_id)

        queryset = queryset.with_cte(edit_cte).with_cte(view_cte).annotate(
            edit=edit_cte.exists(cls._permission_filter),
            view=view_cte.exists(cls._permission_filter),
        )

        if user.is_admin:
            return queryset

        return queryset.filter(
            Q(view=True)
            | Q(edit=True)
            | Q(public=True)
            | Q(uploaded_by=user, contentnode__isnull=True, assessment_item__isnull=True)
        )

    class Admin:
        pass

    def __str__(self):
        return '{checksum}{extension}'.format(checksum=self.checksum, extension='.' + self.file_format.extension)

    def filename(self):
        """
        Returns just the filename of the File in storage, without the path

        e.g. abcd.mp4
        """
        # TODO(aron): write tests for this

        return os.path.basename(self.file_on_disk.name)

    def on_update(self):
        # since modified was added later as a nullable field to File, we don't use a default but
        # instead we'll just make sure it's always updated through our serializers
        self.modified = timezone.now()

    def save(self, set_by_file_on_disk=True, *args, **kwargs):
        """
        Overrider the default save method.
        If the file_on_disk FileField gets passed a content copy:
            1. generate the MD5 from the content copy
            2. fill the other fields accordingly
        """
        from contentcuration.utils.user import calculate_user_storage
        if set_by_file_on_disk and self.file_on_disk:  # if file_on_disk is supplied, hash out the file
            if self.checksum is None or self.checksum == "":
                md5 = hashlib.md5()
                for chunk in self.file_on_disk.chunks():
                    md5.update(chunk)

                self.checksum = md5.hexdigest()
            if not self.file_size:
                self.file_size = self.file_on_disk.size
            if not self.file_format_id:
                ext = os.path.splitext(self.file_on_disk.name)[1].lstrip('.')
                if ext in list(dict(file_formats.choices).keys()):
                    self.file_format_id = ext
                else:
                    raise ValueError("Files of type `{}` are not supported.".format(ext))

        super(File, self).save(*args, **kwargs)

        if self.uploaded_by_id:
            calculate_user_storage(self.uploaded_by_id)

    class Meta:
        indexes = [
            models.Index(fields=['checksum', 'file_size'], name=FILE_DISTINCT_INDEX_NAME),
            models.Index(fields=["-modified"], name=FILE_MODIFIED_DESC_INDEX_NAME),
        ]


@receiver(models.signals.post_delete, sender=File)
def auto_delete_file_on_delete(sender, instance, **kwargs):
    """
    Deletes file from filesystem if no other File objects are referencing the same file on disk
    when corresponding `File` object is deleted.
    Be careful! we don't know if this will work when perform bash delete on File obejcts.
    """
    # Recalculate storage
    from contentcuration.utils.user import calculate_user_storage
    if instance.uploaded_by_id:
        calculate_user_storage(instance.uploaded_by_id)


def delete_empty_file_reference(checksum, extension):
    filename = checksum + '.' + extension
    if not File.objects.filter(checksum=checksum).exists() and not Channel.objects.filter(thumbnail=filename).exists():
        storage_path = generate_object_storage_name(checksum, filename)
        if default_storage.exists(storage_path):
            default_storage.delete(storage_path)


class PrerequisiteContentRelationship(models.Model):
    """
    Predefine the prerequisite relationship between two ContentNode objects.
    """
    target_node = models.ForeignKey(ContentNode, related_name='%(app_label)s_%(class)s_target_node', on_delete=models.CASCADE)
    prerequisite = models.ForeignKey(ContentNode, related_name='%(app_label)s_%(class)s_prerequisite', on_delete=models.CASCADE)

    class Meta:
        unique_together = ['target_node', 'prerequisite']

    def clean(self, *args, **kwargs):
        # self reference exception
        if self.target_node == self.prerequisite:
            raise IntegrityError('Cannot self reference as prerequisite.')
        # immediate cyclic exception
        if PrerequisiteContentRelationship.objects.using(self._state.db) \
                        .filter(target_node=self.prerequisite, prerequisite=self.target_node):
            raise IntegrityError(
                'Note: Prerequisite relationship is directional! %s and %s cannot be prerequisite of each other!'
                % (self.target_node, self.prerequisite))
        # distant cyclic exception
        # elif <this is a nice to have exception, may implement in the future when the priority raises.>
        #     raise Exception('Note: Prerequisite relationship is acyclic! %s and %s forms a closed loop!' % (self.target_node, self.prerequisite))
        super(PrerequisiteContentRelationship, self).clean(*args, **kwargs)

    def save(self, *args, **kwargs):
        self.full_clean()
        super(PrerequisiteContentRelationship, self).save(*args, **kwargs)

    def __unicode__(self):
        return u'%s' % (self.pk)


class RelatedContentRelationship(models.Model):
    """
    Predefine the related relationship between two ContentNode objects.
    """
    contentnode_1 = models.ForeignKey(ContentNode, related_name='%(app_label)s_%(class)s_1', on_delete=models.CASCADE)
    contentnode_2 = models.ForeignKey(ContentNode, related_name='%(app_label)s_%(class)s_2', on_delete=models.CASCADE)

    class Meta:
        unique_together = ['contentnode_1', 'contentnode_2']

    def save(self, *args, **kwargs):
        # self reference exception
        if self.contentnode_1 == self.contentnode_2:
            raise IntegrityError('Cannot self reference as related.')
        # handle immediate cyclic
        if RelatedContentRelationship.objects.using(self._state.db) \
                        .filter(contentnode_1=self.contentnode_2, contentnode_2=self.contentnode_1):
            return  # silently cancel the save
        super(RelatedContentRelationship, self).save(*args, **kwargs)


class Invitation(models.Model):
    """ Invitation to edit channel """
    id = UUIDField(primary_key=True, default=uuid.uuid4)
    accepted = models.BooleanField(default=False)
    declined = models.BooleanField(default=False)
    revoked = models.BooleanField(default=False)
    invited = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='sent_to')
    share_mode = models.CharField(max_length=50, default=EDIT_ACCESS)
    email = models.EmailField(max_length=100, null=True)
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='sent_by', null=True, on_delete=models.CASCADE)
    channel = models.ForeignKey('Channel', null=True, related_name='pending_editors', on_delete=models.CASCADE)
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        verbose_name = "Invitation"
        verbose_name_plural = "Invitations"

    def accept(self):
        user = User.objects.filter(email__iexact=self.email).first()
        if self.channel:
            # channel is a nullable field, so check that it exists.
            if self.share_mode == VIEW_ACCESS:
                self.channel.editors.remove(user)
                self.channel.viewers.add(user)
            else:
                self.channel.viewers.remove(user)
                self.channel.editors.add(user)

    @classmethod
    def filter_edit_queryset(cls, queryset, user):
        if user.is_anonymous:
            return queryset.none()

        if user.is_admin:
            return queryset

        return queryset.filter(
            Q(email__iexact=user.email)
            | Q(sender=user)
            | Q(channel__editors=user)
        ).distinct()

    @classmethod
    def filter_view_queryset(cls, queryset, user):
        if user.is_anonymous:
            return queryset.none()

        if user.is_admin:
            return queryset
        return queryset.filter(
            Q(email__iexact=user.email)
            | Q(sender=user)
            | Q(channel__editors=user)
            | Q(channel__viewers=user)
        ).distinct()


class Task(models.Model):
    """Asynchronous tasks"""
    task_id = UUIDField(db_index=True, default=uuid.uuid4)  # This ID is used as the Celery task ID
    task_type = models.CharField(max_length=50)
    created = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=10)
    is_progress_tracking = models.BooleanField(default=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="task", on_delete=models.CASCADE)
    metadata = JSONField()
    channel_id = DjangoUUIDField(db_index=True, null=True, blank=True)
