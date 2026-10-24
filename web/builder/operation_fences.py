"""World boundaries for an incremental builder operation.

Property guards reject before changing Evennia caches. Signals also cover warmed
handlers, nested Saver values, base typeclasses and direct related-manager writes.
Raw SQL is outside these hooks; lifecycle steps still compare fresh inventories.
"""

from functools import wraps

from django.db.models.signals import m2m_changed, pre_delete, pre_save
from evennia.objects.models import ObjectDB
from evennia.scripts.models import ScriptDB
from evennia.typeclasses.attributes import Attribute
from evennia.typeclasses.tags import Tag

from . import operation_runtime as runtime
from .models import BuildProject

_LINKS = ("db_location_id", "db_home_id", "db_destination_id")
_PROTECTED_ACCESS = {
    "view",
    "search",
    "traverse",
    "edit",
    "delete",
    "control",
    "teleport",
    "teleport_here",
    "get",
    "drop",
    "puppet",
    "attrcreate",
    "attredit",
}


def _identity(value):
    if isinstance(value, str):
        value = value.removeprefix("#")
        if value.isdigit():
            return int(value)
    return getattr(value, "pk", value)


def _alias_names(obj):
    names = (
        list(
            ObjectDB.db_tags.through.objects.filter(
                objectdb_id=obj.pk,
                tag__db_tagtype="alias",
            ).values_list("tag__db_key", flat=True)
        )
        if obj.pk
        else []
    )
    # create_object applies aliases after its initial INSERT. Reserve the whole
    # prospective exit before that INSERT, including categorized alias tuples.
    for item in getattr(obj, "_createdict", {}).get("aliases") or ():
        names.append(item[0] if isinstance(item, (tuple, list)) else item)
    return names


def guard_object(obj, *, field=None, value=None, previous=None, update_fields=None):
    """Check both ends of links and the prospective directed connection slot."""
    if not runtime.world_mutation_is_guarded():
        return
    prospective = {name: getattr(obj, name, None) for name in ("db_key", *_LINKS)}
    if previous and update_fields is not None:
        for name in prospective:
            if name not in update_fields and name.removesuffix("_id") not in update_fields:
                prospective[name] = previous[name]
    if field:
        prospective[field] = _identity(value) if field in _LINKS else value
    targets = [prospective[name] for name in _LINKS]
    targets.extend(getattr(obj, name, None) for name in _LINKS)
    if previous:
        targets.extend(previous[name] for name in _LINKS)
    runtime.assert_mutation_allowed(obj, target_ids=targets)
    if prospective["db_destination_id"] is not None:
        runtime.assert_connection_allowed(
            prospective["db_location_id"],
            names=[prospective["db_key"], *_alias_names(obj)],
            object_id=obj.pk,
        )


def guard_movement(obj, destination, *, use_destination=True):
    target = destination
    if use_destination and getattr(destination, "destination", None):
        target = destination.destination
    runtime.assert_mutation_allowed(
        obj,
        target_ids=(getattr(obj, "db_location_id", None), _identity(destination), _identity(target)),
    )


def access_is_fenced(obj, access_type):
    return access_type in _PROTECTED_ACCESS and runtime.object_is_fenced(obj)


def _restore_fields(instance, previous):
    """A rejected model save must not leave Evennia's shared instance dirty."""
    if previous:
        for name, value in previous.items():
            setattr(instance, name, value)
        instance._state.fields_cache.clear()


def _object_rows_for_attribute(attribute_id):
    return ObjectDB.db_attributes.through.objects.filter(attribute_id=attribute_id).values_list(
        "objectdb_id",
        flat=True,
    )


def _guard_attribute(attribute_id):
    object_ids = list(_object_rows_for_attribute(attribute_id))
    if object_ids:
        runtime.assert_mutation_allowed(target_ids=object_ids)
    for script in ScriptDB.objects.filter(db_attributes__pk=attribute_id):
        runtime.assert_script_mutation_allowed(script)


def _objects_for_tag(tag_id):
    return ObjectDB.objects.filter(db_tags__pk=tag_id)


def _before_save(sender, instance, update_fields=None, **kwargs):
    if not isinstance(instance, (ObjectDB, ScriptDB, Attribute, Tag)) or not runtime.world_mutation_is_guarded():
        return
    previous = None
    try:
        if isinstance(instance, ObjectDB):
            previous = ObjectDB.objects.filter(pk=instance.pk).values().first() if instance.pk else None
            guard_object(instance, previous=previous, update_fields=update_fields)
            if previous and any(
                (update_fields is None or name in update_fields or name.removesuffix("_id") in update_fields)
                and getattr(instance, name) != previous[name]
                for name in (*_LINKS, "db_account_id", "db_sessid", "db_typeclass_path")
            ):
                runtime.assert_connection_room_allowed(instance.pk)
        elif isinstance(instance, ScriptDB):
            runtime.assert_script_mutation_allowed(instance.pk, object_id=instance.db_obj_id)
        elif isinstance(instance, Attribute) and instance.pk:
            _guard_attribute(instance.pk)
        elif isinstance(instance, Tag) and instance.pk:
            for script in ScriptDB.objects.filter(db_tags__pk=instance.pk):
                runtime.assert_script_mutation_allowed(script)
            objects = list(_objects_for_tag(instance.pk))
            if objects:
                runtime.assert_mutation_allowed(target_ids=objects)
            if instance.db_tagtype == "alias":
                for obj in objects:
                    if obj.db_destination_id is not None:
                        runtime.assert_connection_allowed(
                            obj.db_location_id,
                            names=[instance.db_key],
                            object_id=obj.pk,
                        )
    except runtime.OperationError:
        if previous is None and instance.pk:
            model = next(model for model in (ObjectDB, ScriptDB, Attribute, Tag) if isinstance(instance, model))
            previous = model.objects.filter(pk=instance.pk).values().first()
        _restore_fields(instance, previous)
        raise


def _before_delete(sender, instance, **kwargs):
    if isinstance(instance, BuildProject):
        runtime.assert_project_mutation_allowed(instance.pk)
        return
    if isinstance(instance, (ObjectDB.db_tags.through, ObjectDB.db_attributes.through)):
        if runtime.world_mutation_is_guarded():
            runtime.assert_mutation_allowed(instance.objectdb_id)
        return
    if isinstance(instance, (ScriptDB.db_tags.through, ScriptDB.db_attributes.through)):
        if runtime.world_mutation_is_guarded():
            runtime.assert_script_mutation_allowed(instance.scriptdb_id)
        return
    if not isinstance(instance, (ObjectDB, ScriptDB, Attribute, Tag)) or not runtime.world_mutation_is_guarded():
        return
    if isinstance(instance, ObjectDB):
        guard_object(instance)
        runtime.assert_connection_room_allowed(instance.pk)
    elif isinstance(instance, ScriptDB):
        runtime.assert_script_mutation_allowed(instance.pk, object_id=instance.db_obj_id)
    elif isinstance(instance, Attribute):
        _guard_attribute(instance.pk)
    else:
        for script in ScriptDB.objects.filter(db_tags__pk=instance.pk):
            runtime.assert_script_mutation_allowed(script)
        objects = list(_objects_for_tag(instance.pk))
        if objects:
            runtime.assert_mutation_allowed(target_ids=objects)


def _before_relation(sender, instance, action, reverse, pk_set, **kwargs):
    if action not in {"pre_add", "pre_remove", "pre_clear"} or not runtime.world_mutation_is_guarded():
        return
    script_relation = sender in (ScriptDB.db_tags.through, ScriptDB.db_attributes.through)
    tag_relation = sender in (ObjectDB.db_tags.through, ScriptDB.db_tags.through)
    relation_field = "tag_id" if tag_relation else "attribute_id"
    if script_relation:
        script_ids = (
            (
                pk_set
                if pk_set is not None
                else sender.objects.filter(
                    **{relation_field: instance.pk},
                ).values_list("scriptdb_id", flat=True)
            )
            if reverse
            else [instance.pk]
        )
        for script in ScriptDB.objects.filter(pk__in=script_ids):
            runtime.assert_script_mutation_allowed(script)
        return
    if reverse:
        object_ids = (
            pk_set
            if pk_set is not None
            else sender.objects.filter(
                **{relation_field: instance.pk},
            ).values_list("objectdb_id", flat=True)
        )
        objects = list(ObjectDB.objects.filter(pk__in=object_ids))
        tags = [instance] if tag_relation else []
    else:
        objects = [instance]
        tags = Tag.objects.filter(pk__in=pk_set or (), db_tagtype="alias") if tag_relation else []
    for obj in objects:
        guard_object(obj)
        if tag_relation and action == "pre_add" and obj.db_destination_id is not None:
            runtime.assert_connection_allowed(
                obj.db_location_id,
                names=[tag.db_key for tag in tags if tag.db_tagtype == "alias"],
                object_id=obj.pk,
            )


def _guard_saver_mutation(value):
    """Check the persisted owner before a retained Saver changes its memory."""
    if not runtime.world_mutation_is_guarded():
        return
    seen = set()
    while True:
        if id(value) in seen:
            raise runtime.OperationError("Cyclic stored Attribute ownership cannot be mutated")
        seen.add(id(value))
        parent = getattr(value, "_parent", None)
        if parent is None:
            break
        value = parent
    attribute = getattr(value, "_db_obj", None)
    if isinstance(attribute, Attribute) and attribute.pk:
        _guard_attribute(attribute.pk)


def _guarded_saver_method(original):
    @wraps(original)
    def guarded(value, *args, **kwargs):
        _guard_saver_mutation(value)
        return original(value, *args, **kwargs)

    guarded._builder_fence_guarded = True
    return guarded


def _install_saver_guards():
    """Adapt Evennia's save-decorated mutators without replacing their logic.

    Signals and Attribute.value setters run after a Saver has mutated. Guarding
    the decorated class methods also protects wrappers acquired before a claim.
    The adapter is idempotent and preserves the original methods/return values.
    """
    from evennia.utils import dbserialize

    pending = [dbserialize._SaverMutable]
    seen = set()
    while pending:
        cls = pending.pop()
        if cls in seen:
            continue
        seen.add(cls)
        pending.extend(cls.__subclasses__())
        for name, method in list(vars(cls).items()):
            if hasattr(method, "__wrapped__") and not getattr(method, "_builder_fence_guarded", False):
                setattr(cls, name, _guarded_saver_method(method))

    # defaultdict inserts on a missing-key read before its decorated setitem.
    cls = dbserialize._SaverDefaultDict
    original = cls.__getitem__
    if not getattr(original, "_builder_fence_guarded", False):

        @wraps(original)
        def guarded_getitem(value, key):
            if key not in value._data:
                _guard_saver_mutation(value)
            return original(value, key)

        guarded_getitem._builder_fence_guarded = True
        cls.__getitem__ = guarded_getitem


def _guarded_lock_method(original, *, validates=False):
    @wraps(original)
    def guarded(handler, *args, **kwargs):
        validation_only = validates and (args[1] if len(args) > 1 else kwargs.get("validate_only", False))
        if not validation_only and runtime.world_mutation_is_guarded():
            owner = handler.obj
            if isinstance(owner, ObjectDB):
                guard_object(owner)
            elif isinstance(owner, ScriptDB):
                runtime.assert_script_mutation_allowed(owner)
            elif isinstance(owner, Attribute) and owner.pk:
                _guard_attribute(owner.pk)
        return original(handler, *args, **kwargs)

    guarded._builder_fence_guarded = True
    return guarded


def _install_lock_guards():
    """LockHandler changes its authority cache before its model-save hook."""
    from evennia.locks.lockhandler import LockHandler

    for name in ("add", "remove", "delete", "clear", "replace", "append"):
        original = getattr(LockHandler, name)
        if not getattr(original, "_builder_fence_guarded", False):
            setattr(LockHandler, name, _guarded_lock_method(original, validates=name == "add"))


def install_fence_signals():
    _install_saver_guards()
    _install_lock_guards()
    pre_save.connect(_before_save, dispatch_uid="builder.operation_fences.save", weak=False)
    pre_delete.connect(_before_delete, dispatch_uid="builder.operation_fences.delete", weak=False)
    for relation in (
        ObjectDB.db_attributes.through,
        ObjectDB.db_tags.through,
        ScriptDB.db_attributes.through,
        ScriptDB.db_tags.through,
    ):
        m2m_changed.connect(
            _before_relation,
            sender=relation,
            dispatch_uid=f"builder.operation_fences.{relation._meta.label_lower}",
            weak=False,
        )
