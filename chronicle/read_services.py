from collections.abc import Mapping

from django.db.models.functions import Lower
from evennia.objects.models import ObjectDB

from boons.utils import get_boon_totals
from status.models import CharacterStatus

from .models import ChronicleEvent
from .services import available_events, characters_for_account, participant_events, public_events

SUMMARY_ATTRIBUTES = ("stats", "vampire", "pools", "advantages")


def _plain_json(value):
    if isinstance(value, tuple) and (
        (len(value) == 4 and value[0] == "__packed_dbobj__") or (len(value) == 3 and value[0] == "__packed_session__")
    ):
        raise TypeError("Object and session references are not character summary values.")
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported character attribute value: {type(value).__name__}")


def character_summary_for_account(account, character_id):
    # Scalar projections bypass Evennia's process-local ObjectDB/Attribute idmapper
    # caches. PickledObjectField decodes db_value without creating saving wrappers.
    character = characters_for_account(account).filter(pk=character_id).values("id", "db_key").first()
    if character is None:
        return None

    attributes = dict(
        ObjectDB.db_attributes.through.objects.filter(
            objectdb_id=character["id"],
            objectdb__vtm_bio__account=account,
            attribute__db_model__iexact="objectdb",
            attribute__db_category__isnull=True,
            attribute__db_attrtype__isnull=True,
        )
        .annotate(key=Lower("attribute__db_key"))
        .filter(key__in=SUMMARY_ATTRIBUTES)
        .values_list("key", "attribute__db_value")
    )
    status = (
        CharacterStatus.objects.filter(character_id=character["id"], character__vtm_bio__account=account)
        .values("earned_status", "position_status", "temporary_status", "position__name")
        .first()
    )
    ledger = get_boon_totals(character["id"])
    return {
        "id": character["id"],
        "name": character["db_key"],
        **{key: _plain_json(attributes.get(key) or {}) for key in SUMMARY_ATTRIBUTES},
        "status": None
        if status is None
        else {
            "earned": status["earned_status"],
            "position": status["position__name"],
            "total": max(0, min(5, status["earned_status"] + status["position_status"] + status["temporary_status"])),
        },
        "boons": {
            "owed": ledger.total_debt_weight,
            "held": ledger.total_credit_weight,
            "net": ledger.net_weight,
        },
    }


def public_chronicle(limit=100):
    return public_events()[:limit]


def account_chronicle(account, limit=100):
    participant_ids = participant_events(account).values_list("pk", flat=True)
    public = public_events()[:limit]
    personal = ChronicleEvent.objects.filter(pk__in=participant_ids)[:limit]
    events = {event.pk: event for event in (*public, *personal)}
    return sorted(events.values(), key=lambda event: (event.occurred_at, event.pk), reverse=True)[:limit]


def character_chronicle_for_account(account, character_id, limit=100):
    character = characters_for_account(account).filter(pk=character_id).values("id").first()
    if character is None:
        return None
    return available_events(
        ChronicleEvent.objects.filter(
            participants__pk=character["id"],
            visibility=ChronicleEvent.Visibility.PARTICIPANTS,
            status=ChronicleEvent.Status.PUBLISHED,
        ),
        audience="participants",
        account=account,
        character_id=character["id"],
    )[:limit]


def public_lore():
    """Return only curated public V5 reference categories."""
    from world import v5_data

    keys = (
        "ATTRIBUTES",
        "SKILLS",
        "CLANS",
        "DISCIPLINES",
        "PREDATOR_TYPES",
        "BACKGROUNDS",
        "BLOOD_POTENCY",
        "RESONANCES",
    )
    return {key.lower(): getattr(v5_data, key) for key in keys}
