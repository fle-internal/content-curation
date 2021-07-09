import csv
import io
import os
import re
import sys
from builtins import next

from django.conf import settings
from django.contrib.sites.models import Site
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models import Subquery
from django.utils.translation import gettext as _
from le_utils.constants import content_kinds

from contentcuration.models import Channel
from contentcuration.models import generate_storage_url

if not os.path.exists(settings.CSV_ROOT):
    os.makedirs(settings.CSV_ROOT)


# Formatting helpers

def _format_size(num, suffix='B'):
    """ Format sizes """
    for unit in ['', 'K', 'M', 'G', 'T', 'P', 'E', 'Z']:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, 'Yi', suffix)


def generate_user_csv_filename(user):
    directory = os.path.join(settings.CSV_ROOT, "users")
    if not os.path.exists(directory):
        os.makedirs(directory)
    email = re.sub(r'([^\s\w]|_)+', '', user.email.split('.')[0])
    return os.path.join(directory, "{}{}- {} {} Data.csv".format(email, user.id, user.first_name, user.last_name))


def _write_user_row(file, writer, domain):
    filename = '{}.{}'.format(file['checksum'], file['file_format__extension'])
    writer.writerow([
        file['channel_name'] or _("No Channel"),
        file['contentnode__title'] or _("No resource"),
        next((k[1] for k in content_kinds.choices if k[0] == file['contentnode__kind_id']), ''),
        file['original_filename'],
        _format_size(file['file_size'] or 0),
        generate_storage_url(filename),
        file['contentnode__description'],
        file['contentnode__author'],
        file['language__readable_name'] or file['contentnode__language__readable_name'],
        file['contentnode__license__license_name'],
        file['contentnode__license_description'],
        file['contentnode__copyright_holder'],
    ])


def write_user_csv(user, path=None):
    csv_path = path or generate_user_csv_filename(user)
    mode = 'wb'
    encoding = None
    # On Python 3,
    if sys.version_info.major == 3:
        mode = 'w'
        encoding = 'utf-8'
    with io.open(csv_path, mode, encoding=encoding) as csvfile:
        writer = csv.writer(csvfile, delimiter=',', quoting=csv.QUOTE_MINIMAL)

        writer.writerow([_('Channel'), _('Title'), _('Kind'), _('Filename'), _('File Size'), _('URL'), _('Description'),
                         _('Author'), _('Language'), _('License'), _('License Description'), _('Copyright Holder')])

        domain = Site.objects.get(pk=1).domain

        # Get all user files
        channel_query = Channel.objects.filter(
            Q(main_tree__tree_id=OuterRef("contentnode__tree_id")) |
            Q(trash_tree__tree_id=OuterRef("contentnode__tree_id"))
        )

        user_files = user.files \
            .select_related('language', 'contentnode', 'file_format') \
            .annotate(channel_name=Subquery(channel_query.values_list("name", flat=True)[:1])) \
            .values(
                'channel_name',
                'original_filename',
                'file_size',
                'checksum',
                'file_format__extension',
                'language__readable_name',
                'contentnode__title',
                'contentnode__language__readable_name',
                'contentnode__license__license_name',
                'contentnode__kind_id',
                'contentnode__description',
                'contentnode__author',
                'contentnode__provider',
                'contentnode__aggregator',
                'contentnode__license_description',
                'contentnode__copyright_holder',
            )
        for file in user_files:
            _write_user_row(file, writer, domain)

        for file in user.staged_files.all():
            file_size = _format_size(file.file_size)
            writer.writerow([_("No Channel"), _("No Resource"), "", _("Staged File"), file_size, "", "", "", "", "", "", ""])

    return csv_path
