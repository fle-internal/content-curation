import traceback

from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404
from django_bulk_update.helper import bulk_update
from django_filters.constants import EMPTY_VALUES
from django_filters.rest_framework import FilterSet
from rest_framework.generics import get_object_or_404
from rest_framework.mixins import DestroyModelMixin
from rest_framework.response import Response
from rest_framework.serializers import ListSerializer
from rest_framework.serializers import ModelSerializer
from rest_framework.serializers import raise_errors_on_nested_writes
from rest_framework.serializers import Serializer
from rest_framework.serializers import ValidationError
from rest_framework.settings import api_settings
from rest_framework.status import HTTP_201_CREATED
from rest_framework.utils import html
from rest_framework.utils import model_meta
from rest_framework.viewsets import ReadOnlyModelViewSet

from contentcuration.viewsets.common import MissingRequiredParamsException


class BulkModelSerializer(ModelSerializer):
    def __init__(self, *args, **kwargs):
        super(BulkModelSerializer, self).__init__(*args, **kwargs)
        # Track any changes that should be propagated back to the frontend
        self.changes = []

    @classmethod
    def id_attr(cls):
        ModelClass = cls.Meta.model
        info = model_meta.get_field_info(ModelClass)
        return getattr(cls.Meta, "update_lookup_field", info.pk.name)

    def to_internal_value(self, data):
        ret = super(BulkModelSerializer, self).to_internal_value(data)

        id_attr = self.id_attr()

        # add update_lookup_field field back to validated data
        # since super by default strips out read-only fields
        # hence id will no longer be present in validated_data
        if all((isinstance(self.root, BulkListSerializer), id_attr,)):
            id_field = self.fields[id_attr]
            id_value = id_field.get_value(data)

            ret[id_attr] = id_value

        return ret

    def update(self, instance, validated_data):
        # To ensure caution, require nested_writes to be explicitly allowed
        if not (hasattr(self.Meta, "nested_writes") and self.Meta.nested_writes):
            raise_errors_on_nested_writes("update", self, validated_data)
        info = model_meta.get_field_info(instance)

        # Simply set each attribute on the instance, and then save it.
        # Note that unlike `.create()` we don't need to treat many-to-many
        # relationships as being a special case. During updates we already
        # have an instance pk for the relationships to be associated with.
        self.m2m_fields = []
        for attr, value in validated_data.items():
            if attr in info.relations and info.relations[attr].to_many:
                self.m2m_fields.append((attr, value))
            else:
                setattr(instance, attr, value)

        if hasattr(instance, "on_update") and callable(instance.on_update):
            instance.on_update()

        return instance

    def post_save_update(self, instance, m2m_fields=None):
        m2m_fields = m2m_fields if m2m_fields is not None else self.m2m_fields
        # Note that many-to-many fields are set after updating instance.
        # Setting m2m fields triggers signals which could potentially change
        # updated instance and we do not want it to collide with .update()
        if m2m_fields:
            for attr, value in m2m_fields:
                field = getattr(instance, attr)
                field.set(value)

    def create(self, validated_data):
        # To ensure caution, require nested_writes to be explicitly allowed
        if not (hasattr(self.Meta, "nested_writes") and self.Meta.nested_writes):
            raise_errors_on_nested_writes("create", self, validated_data)

        ModelClass = self.Meta.model

        # Remove many-to-many relationships from validated_data.
        # They are not valid arguments to the default `.create()` method,
        # as they require that the instance has already been saved.
        info = model_meta.get_field_info(ModelClass)
        self.many_to_many = {}
        for field_name, relation_info in info.relations.items():
            if relation_info.to_many and (field_name in validated_data):
                self.many_to_many[field_name] = validated_data.pop(field_name)

        instance = ModelClass(**validated_data)

        if hasattr(instance, "on_create") and callable(instance.on_create):
            instance.on_create()

        return instance

    def post_save_create(self, instance, many_to_many=None):
        many_to_many = many_to_many if many_to_many is not None else self.many_to_many
        # Save many-to-many relationships after the instance is created.
        if many_to_many:
            for field_name, value in many_to_many.items():
                field = getattr(instance, field_name)
                field.set(value)


class BulkListSerializer(ListSerializer):
    def __init__(self, *args, **kwargs):
        super(BulkListSerializer, self).__init__(*args, **kwargs)
        # Track any changes that should be propagated back to the frontend
        self.changes = []

    def to_internal_value(self, data):
        """
        List of dicts of native values <- List of dicts of primitive datatypes.
        Modified from https://github.com/encode/django-rest-framework/blob/master/rest_framework/serializers.py
        based on suggestions from https://github.com/miki725/django-rest-framework-bulk/issues/68
        This is to prevent an error whereby the DRF Unique validator fails when the instance on the child
        serializer is a queryset and not an object.
        """
        if html.is_html_input(data):
            data = html.parse_html_list(data, default=[])

        if not isinstance(data, list):
            message = self.error_messages["not_a_list"].format(
                input_type=type(data).__name__
            )
            raise ValidationError(
                {api_settings.NON_FIELD_ERRORS_KEY: [message]}, code="not_a_list"
            )

        if not self.allow_empty and len(data) == 0:
            message = self.error_messages["empty"]
            raise ValidationError(
                {api_settings.NON_FIELD_ERRORS_KEY: [message]}, code="empty"
            )

        ret = []
        errors = []

        data_lookup = self.instance.in_bulk() if self.instance else {}
        id_attr = self.child.id_attr()

        for item in data:
            try:
                # prepare child serializer to only handle one instance
                self.child.instance = data_lookup.get(item[id_attr])
                self.child.initial_data = item
                validated = self.child.run_validation(item)
            except ValidationError as exc:
                errors.append(exc.detail)
            else:
                ret.append(validated)
                errors.append({})

        if any(errors):
            raise ValidationError(errors)

        return ret

    def update(self, queryset, all_validated_data):
        id_attr = self.child.id_attr()
        concrete_fields = set(
            f.name for f in self.child.Meta.model._meta.concrete_fields
        )

        all_validated_data_by_id = {}

        properties_to_update = set()

        for obj in all_validated_data:
            obj_id = obj.pop(id_attr)
            if obj.keys():
                all_validated_data_by_id[obj_id] = obj
                properties_to_update.update(obj.keys())

        properties_to_update = properties_to_update.intersection(concrete_fields)

        # since this method is given a queryset which can have many
        # model instances, first find all objects to update
        # and only then update the models
        objects_to_update = queryset.filter(
            **{"{}__in".format(id_attr): all_validated_data_by_id.keys()}
        ).only(*properties_to_update)

        if len(all_validated_data_by_id) != objects_to_update.count():
            raise ValidationError("Could not find all objects to update.")

        updated_objects = []

        m2m_fields_by_id = {}

        for obj in objects_to_update:
            # Coerce to string as some ids are of the UUID class
            obj_id = str(getattr(obj, id_attr))
            obj_validated_data = all_validated_data_by_id.get(obj_id)

            # Reset the child serializer changes attribute
            self.child.changes = []
            # use model serializer to actually update the model
            # in case that method is overwritten

            instance = self.child.update(obj, obj_validated_data)
            # If the update method does not return an instance for some reason
            # do not try to run further updates on the model, as there is no
            # object to udpate.
            if instance:
                m2m_fields_by_id[obj_id] = self.child.m2m_fields
                updated_objects.append(instance)
            # Collect any registered changes from this run of the loop
            self.changes.extend(self.child.changes)

        bulk_update(objects_to_update, update_fields=properties_to_update)

        for obj in objects_to_update:
            obj_id = getattr(obj, id_attr)
            m2m_fields = m2m_fields_by_id.get(obj_id)
            self.child.post_save_update(obj, m2m_fields)

        return updated_objects

    def create(self, validated_data):
        ModelClass = self.child.Meta.model
        objects_to_create = []
        many_to_many_tuples = []
        for model_data in validated_data:
            # Reset the child serializer changes attribute
            self.child.changes = []
            object_to_create = self.child.create(model_data)
            objects_to_create.append(object_to_create)
            many_to_many_tuples.append(self.child.many_to_many)
            # Collect any registered changes from this run of the loop
            self.changes.extend(self.child.changes)
        try:
            created_objects = ModelClass._default_manager.bulk_create(objects_to_create)
        except TypeError:
            tb = traceback.format_exc()
            msg = (
                "Got a `TypeError` when calling `%s.%s.create()`. "
                "This may be because you have a writable field on the "
                "serializer class that is not a valid argument to "
                "`%s.%s.create()`. You may need to make the field "
                "read-only, or override the %s.create() method to handle "
                "this correctly.\nOriginal exception was:\n %s"
                % (
                    ModelClass.__name__,
                    ModelClass._default_manager.name,
                    ModelClass.__name__,
                    ModelClass._default_manager.name,
                    self.__class__.__name__,
                    tb,
                )
            )
            raise TypeError(msg)
        for instance, many_to_many in zip(created_objects, many_to_many_tuples):
            self.child.post_save_create(instance, many_to_many)
        return created_objects


class ReadOnlyValuesViewset(ReadOnlyModelViewSet):
    """
    A viewset that uses a values call to get all model/queryset data in
    a single database query, rather than delegating serialization to a
    DRF ModelSerializer.
    """

    # A tuple of values to get from the queryset
    values = None
    # A map of target_key, source_key where target_key is the final target_key that will be set
    # and source_key is the key on the object retrieved from the values call.
    # Alternatively, the source_key can be a callable that will be passed the object and return
    # the value for the target_key. This callable can also pop unwanted values from the obj
    # to remove unneeded keys from the object as a side effect.
    field_map = {}

    def __init__(self, *args, **kwargs):
        viewset = super(ReadOnlyValuesViewset, self).__init__(*args, **kwargs)
        if not isinstance(self.values, tuple):
            raise TypeError("values must be defined as a tuple")
        self._values = tuple(self.values)
        if not isinstance(self.field_map, dict):
            raise TypeError("field_map must be defined as a dict")
        self._field_map = self.field_map.copy()
        return viewset

    @classmethod
    def id_attr(cls):
        if cls.serializer_class is not None and hasattr(
            cls.serializer_class, "id_attr"
        ):
            return cls.serializer_class.id_attr()
        return None

    def get_serializer_class(self):
        if self.serializer_class is not None:
            return self.serializer_class
        # Hack to prevent the renderer logic from breaking completely.
        return Serializer

    def get_edit_queryset(self):
        """
        Return a filtered copy of the queryset to only the objects
        that a user is able to edit, rather than view.
        """
        return self.get_queryset()

    def _get_object_from_queryset(self, queryset):
        """
        Returns the object the view is displaying.
        We override this to remove the DRF default behaviour
        of filtering the queryset.
        (rtibbles) There doesn't seem to be a use case for
        querying a detail endpoint and also filtering by query
        parameters that might result in a 404.
        """
        # Perform the lookup filtering.
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field

        assert lookup_url_kwarg in self.kwargs, (
            "Expected view %s to be called with a URL keyword argument "
            'named "%s". Fix your URL conf, or set the `.lookup_field` '
            "attribute on the view correctly."
            % (self.__class__.__name__, lookup_url_kwarg)
        )

        filter_kwargs = {self.lookup_field: self.kwargs[lookup_url_kwarg]}
        obj = get_object_or_404(queryset, **filter_kwargs)

        # May raise a permission denied
        self.check_object_permissions(self.request, obj)

        return obj

    def get_object(self):
        return self._get_object_from_queryset(self.get_queryset())

    def get_edit_object(self):
        return self._get_object_from_queryset(self.get_edit_queryset())

    def annotate_queryset(self, queryset):
        return queryset

    def prefetch_queryset(self, queryset):
        return queryset

    def _map_fields(self, item):
        for key, value in self._field_map.items():
            if callable(value):
                item[key] = value(item)
            elif value in item:
                item[key] = item.pop(value)
            else:
                item[key] = value
        return item

    def consolidate(self, items, queryset):
        return items

    def _cast_queryset_to_values(self, queryset):
        queryset = self.annotate_queryset(queryset)
        return queryset.values(*self._values)

    def serialize(self, queryset):
        return self.consolidate(list(map(self._map_fields, queryset or [])), queryset)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.prefetch_queryset(self.get_queryset()))
        queryset = self._cast_queryset_to_values(queryset)

        page = self.paginate_queryset(queryset)

        if page is not None:
            return self.get_paginated_response(self.serialize(page))

        return Response(self.serialize(queryset))

    def serialize_object(self, pk):
        queryset = self.prefetch_queryset(self.get_queryset())
        try:
            return self.serialize(
                self._cast_queryset_to_values(queryset.filter(pk=pk))
            )[0]
        except IndexError:
            raise Http404(
                "No %s matches the given query." % queryset.model._meta.object_name
            )

    def retrieve(self, request, pk, *args, **kwargs):
        return Response(self.serialize_object(pk))


class ValuesViewset(ReadOnlyValuesViewset, DestroyModelMixin):
    def _map_create_change(self, change):
        return dict(
            [(k, v) for k, v in change["obj"].items()]
            + [(self.id_attr(), change["key"])]
        )

    def _map_update_change(self, change):
        return dict(
            [(k, v) for k, v in change["mods"].items()]
            + [(self.id_attr(), change["key"])]
        )

    def _map_delete_change(self, change):
        return change["key"]

    def perform_create(self, serializer):
        instance = serializer.save()
        instance.save()
        serializer.post_save_create(instance)

    def create_from_changes(self, changes):
        errors = []
        changes_to_return = []

        for change in changes:
            serializer = self.get_serializer(data=self._map_create_change(change))
            if serializer.is_valid():
                self.perform_create(serializer)
                if serializer.changes:
                    changes_to_return.extend(serializer.changes)
            else:
                change.update({"errors": serializer.errors})
                errors.append(change)

        return errors, changes_to_return

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        instance = serializer.instance
        return Response(self.serialize_object(instance.id), status=HTTP_201_CREATED)

    def perform_update(self, serializer):
        instance = serializer.save()
        instance.save()
        serializer.post_save_update(instance)

    def update_from_changes(self, changes):
        errors = []
        changes_to_return = []
        queryset = self.get_edit_queryset().order_by()
        for change in changes:
            try:
                instance = queryset.get(**{self.id_attr(): change["key"]})
                serializer = self.get_serializer(
                    instance, data=self._map_update_change(change), partial=True
                )
                if serializer.is_valid():
                    self.perform_update(serializer)
                    if serializer.changes:
                        changes_to_return.extend(serializer.changes)
                else:
                    change.update({"errors": serializer.errors})
                    errors.append(change)
            except ObjectDoesNotExist:
                # Should we also check object permissions here and return a different
                # error if the user can view the object but not edit it?
                change.update({"errors": ValidationError("Not found").detail})
                errors.append(change)
        return errors, changes_to_return

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_edit_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        return Response(self.serialize_object(instance.id))

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def delete_from_changes(self, changes):
        errors = []
        changes_to_return = []
        queryset = self.get_edit_queryset().order_by()
        for change in changes:
            try:
                instance = queryset.get(**{self.id_attr(): change["key"]})

                instance.delete()
            except ObjectDoesNotExist:
                # Should we also check object permissions here and return a different
                # error if the user can view the object but not edit it?
                change.update({"errors": ValidationError("Not found").detail})
                errors.append(change)
        return errors, changes_to_return


class BulkCreateMixin(object):
    def perform_bulk_create(self, serializer):
        serializer.save()

    def create_from_changes(self, changes):
        data = list(map(self._map_create_change, changes))
        serializer = self.get_serializer(data=data, many=True)
        errors = []
        if serializer.is_valid():
            self.perform_bulk_create(serializer)
        else:
            valid_data = []
            for error, datum in zip(serializer.errors, changes):
                if error:
                    datum.update({"errors": error})
                    errors.append(datum)
                else:
                    valid_data.append(datum)
            if valid_data:
                serializer = self.get_serializer(data=valid_data, many=True)
                # This should now not raise an exception as we have filtered
                # all the invalid objects, but we still need to call is_valid
                # before DRF will let us save them.
                serializer.is_valid(raise_exception=True)
                self.perform_bulk_create(serializer)
        return errors, serializer.changes


class BulkUpdateMixin(object):
    def perform_bulk_update(self, serializer):
        serializer.save()

    def update_from_changes(self, changes):
        data = list(map(self._map_update_change, changes))
        queryset = self.get_edit_queryset().order_by()
        serializer = self.get_serializer(queryset, data=data, many=True, partial=True)
        errors = []

        if serializer.is_valid():
            self.perform_bulk_update(serializer)
        else:
            valid_data = []
            for error, datum in zip(serializer.errors, changes):
                if error:
                    # If the user does not have permission to write to this object
                    # it will throw a uniqueness validation error when trying to
                    # validate the id attribute for the change
                    # intercept this and replace with not found.

                    if self.id_attr() in error and any(
                        map(
                            lambda x: getattr(x, "code", None) == "unique",
                            error[self.id_attr()],
                        )
                    ):
                        error = ValidationError("Not found").detail
                    datum.update({"errors": error})
                    errors.append(datum)
                else:
                    valid_data.append(datum)
            if valid_data:
                serializer = self.get_serializer(
                    queryset, data=valid_data, many=True, partial=True
                )
                # This should now not raise an exception as we have filtered
                # all the invalid objects, but we still need to call is_valid
                # before DRF will let us save them.
                serializer.is_valid(raise_exception=True)
                self.perform_bulk_update(serializer)
        return errors, serializer.changes


class BulkDeleteMixin(object):
    def delete_from_changes(self, changes):
        ids = list(map(self._map_delete_change, changes))
        errors = []
        changes_to_return = []
        try:
            self.get_edit_queryset().filter(
                **{"{}__in".format(self.id_attr()): ids}
            ).delete()
        except Exception:
            errors = [
                {
                    "key": not_deleted_id,
                    "errors": ValidationError("Could not be deleted").detail,
                }
                for not_deleted_id in ids
            ]
        return errors, changes_to_return


class CopyMixin(object):
    def copy_from_changes(self, changes):
        errors = []
        changes_to_return = []
        for copy in changes:
            # Copy change will have key, must also have other attributes, defined in `copy`
            copy_errors, copy_changes = self.copy(
                copy["key"], from_key=copy["from_key"], **copy["mods"]
            )
            if copy_errors:
                copy.update({"errors": copy_errors})
                errors.append(copy)
            if copy_changes:
                changes_to_return.extend(copy_changes)
        return errors, changes_to_return


class RelationMixin(object):
    def create_relation_from_changes(self, changes):
        errors = []
        changes_to_return = []
        for relation in changes:
            # Create relation will have an object that at minimum has the keys
            # for the two objects being related.
            relation_errors, relation_changes = self.create_relation(relation)
            if relation_errors:
                relation.update({"errors": relation_errors})
                errors.append(relation)
            if relation_changes:
                changes_to_return.extend(relation_changes)
        return errors, changes_to_return

    def delete_relation_handler(self, changes):
        errors = []
        changes_to_return = []
        for relation in changes:
            # Delete relation will have an object that at minimum has the keys
            # for the two objects whose relationship is being destroyed.
            relation_errors, relation_changes = self.delete_relation(relation)
            if relation_errors:
                relation.update({"errors": relation_errors})
                errors.append(relation)
            if relation_changes:
                changes_to_return.extend(relation_changes)
        return errors, changes_to_return


class RequiredFilterSet(FilterSet):
    @property
    def qs(self):
        has_filtering_queries = False
        if self.form.is_valid():
            for name, filter_ in self.filters.items():
                value = self.form.cleaned_data.get(name)

                if value not in EMPTY_VALUES:
                    has_filtering_queries = True
                    break
        if not has_filtering_queries:
            raise MissingRequiredParamsException("No valid filter parameters supplied")
        return super(FilterSet, self).qs
