from collections.abc import Mapping

from boons.utils import get_boon_totals
from status.models import CharacterStatus

from .models import ChronicleEvent
from .services import character_owned_by, participant_events, public_events


def _plain_json(value):
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported character attribute value: {type(value).__name__}")


def character_summary_for_account(account, character_id):
    character = character_owned_by(account, character_id)
    if character is None:
        return None

    status = CharacterStatus.objects.filter(character=character).first()
    boons = get_boon_totals(character)
    return {
        "id": character.pk,
        "name": character.key,
        "stats": _plain_json(character.db.stats or {}),
        "vampire": _plain_json(character.db.vampire or {}),
        "pools": _plain_json(character.db.pools or {}),
        "advantages": _plain_json(character.db.advantages or {}),
        "status": None
        if status is None
        else {
            "earned": status.earned_status,
            "position": status.position.name if status.position_id else None,
            "total": status.total_status,
        },
        "boons": {
            "owed": boons.total_debt_weight,
            "held": boons.total_credit_weight,
            "net": boons.net_weight,
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
    character = character_owned_by(account, character_id)
    if character is None:
        return None
    return ChronicleEvent.objects.filter(
        participants=character,
        visibility=ChronicleEvent.Visibility.PARTICIPANTS,
        status=ChronicleEvent.Status.PUBLISHED,
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
