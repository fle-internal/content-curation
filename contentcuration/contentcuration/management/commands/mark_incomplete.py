import logging as logmodule
import time

from django.core.management.base import BaseCommand
from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Q
from le_utils.constants import content_kinds
from le_utils.constants import exercises

from contentcuration.models import AssessmentItem
from contentcuration.models import ContentNode
from contentcuration.models import File

logmodule.basicConfig(level=logmodule.INFO)
logging = logmodule.getLogger('command')


CHUNKSIZE = 1000


class Command(BaseCommand):

    def handle(self, *args, **options):
        start = time.time()

        # Mark invalid topics
        topicstart = time.time()
        logging.info('Marking topics invalid...')
        query = ContentNode.objects.filter(kind_id=content_kinds.TOPIC, title='', complete__isnull=True).values_list('id', flat=True)
        i = 0
        count = 0
        node_ids = query[i:i + CHUNKSIZE]
        while node_ids.exists():
            count += node_ids.update(complete=False)
            i += CHUNKSIZE
            logging.info("Cumulatively marked {} nodes".format(count))
            node_ids = query[i:i + CHUNKSIZE]
        logging.info('Marked {} invalid topics (finished in {})'.format(count, time.time() - topicstart))

        # Mark valid topics
        topicstart = time.time()
        logging.info('Marking topics valid...')
        query = ContentNode.objects.filter(kind_id=content_kinds.TOPIC, complete__isnull=True).values_list('id', flat=True)
        i = 0
        count = 0
        node_ids = query[i:i + CHUNKSIZE]
        while node_ids.exists():
            count += node_ids.update(complete=True)
            i += CHUNKSIZE
            logging.info("Cumulatively marked {} nodes".format(count))
            node_ids = query[i:i + CHUNKSIZE]
        logging.info('Marked {} valid topics (finished in {})'.format(count, time.time() - topicstart))

        # Mark invalid file resources
        resourcestart = time.time()
        logging.info('Marking file resources invalid...')
        i = 0
        count = 0
        valid_count = 0
        file_check_query = File.objects.filter(preset__supplementary=False, contentnode=OuterRef("id"))
        query = ContentNode.objects \
            .exclude(kind_id=content_kinds.TOPIC) \
            .exclude(kind_id=content_kinds.EXERCISE) \
            .filter(complete__isnull=True) \
            .values_list('id', flat=True)
        node_ids = query[i:i + CHUNKSIZE]
        while node_ids:
            nodes = ContentNode.objects.filter(pk__in=node_ids) \
                .annotate(has_files=Exists(file_check_query)) \
                .filter(
                    Q(title='') |
                    Q(has_files=False) |
                    Q(license=None) |
                    (Q(license__is_custom=True) & (Q(license_description=None) | Q(license_description=''))) |
                    (Q(license__copyright_holder_required=True) & (Q(copyright_holder=None) | Q(copyright_holder='')))
                ).values_list('id', flat=True)
            count += ContentNode.objects.filter(pk__in=nodes).update(complete=False)
            logging.info("Cumulatively marked {} nodes invalid".format(count))
            valid_count += ContentNode.objects.filter(complete__isnull=True, pk__in=node_ids).update(complete=False)
            logging.info("Cumulatively marked {} nodes valid".format(valid_count))
            i += CHUNKSIZE
            node_ids = query[i:i + CHUNKSIZE]
        logging.info('Marked {} invalid and {} valid file resources (finished in {})'.format(count, valid_count, time.time() - resourcestart))

        # Mark invalid exercises
        exercisestart = time.time()
        logging.info('Marking exercises...')
        i = 0
        count = 0
        valid_count = 0
        exercise_check_query = AssessmentItem.objects.filter(contentnode=OuterRef('id')) \
            .exclude(type=exercises.PERSEUS_QUESTION)\
            .filter(
                Q(question='') |
                Q(answers='[]') |
                (~Q(type=exercises.INPUT_QUESTION) & ~Q(answers__iregex=r'"correct":\s*true'))  # hack to check if no correct answers
            )
        query = ContentNode.objects \
            .filter(kind_id=content_kinds.EXERCISE) \
            .filter(complete__isnull=True) \
            .values_list('id', flat=True)
        node_ids = query[i:i + CHUNKSIZE]
        while node_ids:
            nodes = ContentNode.objects.filter(pk__in=node_ids) \
                .annotate(
                    has_questions=Exists(AssessmentItem.objects.filter(contentnode=OuterRef("id"))),
                    invalid_exercise=Exists(exercise_check_query)
                ).filter(
                    Q(title='') |
                    Q(license=None) |
                    (Q(license__is_custom=True) & (Q(license_description=None) | Q(license_description=''))) |
                    (Q(license__copyright_holder_required=True) & (Q(copyright_holder=None) | Q(copyright_holder=''))) |
                    Q(has_questions=False) |
                    Q(invalid_exercise=True) |
                    ~Q(extra_fields__has_key='type') |
                    Q(extra_fields__type=exercises.M_OF_N) & (
                        ~Q(extra_fields__has_key='m') | ~Q(extra_fields__has_key='n')
                    )
                ).values_list('id', flat=True)
            count += ContentNode.objects.filter(pk__in=nodes).update(complete=False)
            logging.info("Cumulatively marked {} nodes invalid".format(count))
            valid_count += ContentNode.objects.filter(complete__isnull=True, pk__in=node_ids).update(complete=False)
            logging.info("Cumulatively marked {} nodes valid".format(valid_count))
            i += CHUNKSIZE
            node_ids = query[i:i + CHUNKSIZE]

        logging.info('Marked {} invalid and {} valid exercises (finished in {})'.format(count, valid_count, time.time() - exercisestart))

        logging.info('Mark incomplete command completed in {}s'.format(time.time() - start))
