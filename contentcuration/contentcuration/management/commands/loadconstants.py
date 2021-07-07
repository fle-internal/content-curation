import logging as logmodule
from builtins import object
from builtins import str

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.cache import cache
from django.core.management.base import BaseCommand
from le_utils.constants import content_kinds
from le_utils.constants import file_formats
from le_utils.constants import format_presets
from le_utils.constants import languages
from le_utils.constants import licenses
from readonly.exceptions import DatabaseWriteDenied

from contentcuration import models

logging = logmodule.getLogger(__name__)


class ConstantGenerator(object):
    id_field = "id"

    def generate_list(self):
        # Get constants from subclass' default_list (from le-utils pkg)
        return [
            {
                "model": self.model,
                "pk": self.id_field,
                "fields": self.get_dict(constant),
            }
            for constant in self.default_list
        ]

    def get_dict(self, constant):
        return constant._asdict()


class LicenseGenerator(ConstantGenerator):
    module = licenses
    filename = "licenselookup.json"
    default_list = licenses.LICENSELIST
    model = models.License

    def get_dict(self, constant):
        return {
            "id": constant.id,
            "license_name": constant.name,
            "exists": constant.exists,
            "license_url": constant.url,
            "license_description": constant.description,
            "copyright_holder_required": constant.copyright_holder_required,
            "is_custom": constant.custom,
        }


class KindGenerator(ConstantGenerator):
    module = content_kinds
    filename = "kindlookup.json"
    default_list = content_kinds.KINDLIST
    model = models.ContentKind
    id_field = "kind"

    def get_dict(self, constant):
        return {
            "kind": constant.name,
        }


class LanguageGenerator(ConstantGenerator):
    module = languages
    filename = "languagelookup.json"
    default_list = languages.LANGUAGELIST
    model = models.Language

    def get_dict(self, constant):
        return {
            "id": constant.code,
            "lang_code": constant.primary_code,
            "lang_subcode": constant.subcode,
            "readable_name": constant.name,
            "native_name": constant.native_name,
            "lang_direction": languages.getlang_direction(constant.primary_code),
        }


class FormatGenerator(ConstantGenerator):
    module = file_formats
    filename = "formatlookup.json"
    default_list = file_formats.FORMATLIST
    model = models.FileFormat
    id_field = "extension"

    def get_dict(self, constant):
        return {
            "extension": constant.id,
            "mimetype": constant.mimetype,
        }


class PresetGenerator(ConstantGenerator):
    module = format_presets
    filename = "presetlookup.json"
    default_list = format_presets.PRESETLIST
    model = models.FormatPreset

    def get_dict(self, constant):
        return {
            "id": constant.id,
            "readable_name": constant.readable_name,
            "multi_language": constant.multi_language,
            "supplementary": constant.supplementary,
            "thumbnail": constant.thumbnail,
            "subtitle": constant.subtitle,
            "display": constant.display,
            "order": constant.order,
            "kind_id": constant.kind,
            "allowed_formats": constant.allowed_formats,
        }


SITES = [
    {
        "model": Site,
        "pk": "id",
        "fields": {
            "id": 1,
            "name": "Kolibri Studio",
            "domain": "studio.learningequality.org",
        },
    },
    {
        "model": Site,
        "pk": "id",
        "fields": {
            "id": 2,
            "name": "Kolibri Studio (Debug Mode)",
            "domain": "127.0.0.1:8000",
        },
    },
    {
        "model": Site,
        "pk": "id",
        "fields": {
            "id": 3,
            "name": "Kolibri Studio (Develop)",
            "domain": "develop.contentworkshop.learningequality.org",
        },
    },
]

LICENSES = LicenseGenerator().generate_list()
FILE_FORMATS = FormatGenerator().generate_list()
KINDS = KindGenerator().generate_list()
PRESETS = PresetGenerator().generate_list()
LANGUAGES = LanguageGenerator().generate_list()

CONSTANTS = [SITES, LICENSES, KINDS, FILE_FORMATS, PRESETS, LANGUAGES]


class EarlyExit(BaseException):
    def __init__(self, message, db_path):
        self.message = message
        self.db_path = db_path


class Command(BaseCommand):
    def add_arguments(self, parser):
        pass

    def handle(self, *args, **options):
        try:
            self.stdout.write("***** Loading Constants *****")
            for constant_list in CONSTANTS:
                current_model = ""
                new_model_count = 0
                for constant in constant_list:
                    current_model = constant["model"].__name__
                    if current_model in cache:
                        cache.delete(current_model)
                    obj, isNew = constant["model"].objects.update_or_create(
                        **{constant["pk"]: constant["fields"][constant["pk"]]}
                    )
                    new_model_count += 1 if isNew else 0
                    for attr, value in list(constant["fields"].items()):
                        field = obj._meta.get_field(attr)
                        if field.many_to_many:
                            getattr(obj, attr).set(value)
                        else:
                            setattr(obj, attr, value)

                    obj.save()
                self.stdout.write(
                    "{0}: {1} constants saved ({2} new)".format(
                        str(current_model), len(constant_list), new_model_count
                    )
                )

            # Create garbage node
            garbage_node, _new = models.ContentNode.objects.get_or_create(
                pk=settings.ORPHANAGE_ROOT_ID, kind_id=content_kinds.TOPIC
            )
            garbage_node.title = "Garbage Node Root"
            garbage_node.description = "This node as the default parent for nodes not associated with a channel"
            garbage_node.save()

            self.stdout.write("************ DONE. ************")

        except DatabaseWriteDenied:
            logging.warning("DB is in read-only mode, skipping loadconstants")

        except EarlyExit as e:
            logging.warning("Exited early due to {message}.".format(message=e.message))
            self.stdout.write(
                "You can find your database in {path}".format(path=e.db_path)
            )
