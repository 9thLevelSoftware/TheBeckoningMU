"""
Trigger script management for timed room triggers.

Handles creation, deletion, and lifecycle of Evennia Scripts
attached to rooms for timed trigger execution.
"""

import logging
from typing import Any

from evennia.utils.create import create_script

logger = logging.getLogger(__name__)


def start_timed_trigger(room, trigger_data: dict[str, Any]):
    """
    Create and start the timed-trigger Script for one trigger on one room.

    Raises on any failure (the sandbox build relies on that to undo itself).
    An existing script for the same trigger on the same room is returned
    rather than duplicated; scripts on other rooms are never considered.
    """
    from evennia.scripts.models import ScriptDB

    trigger_id = trigger_data.get("id")
    if not trigger_id:
        raise ValueError("Cannot create a timed trigger without an id")
    key = f"trigger_{trigger_id}"

    existing = ScriptDB.objects.filter(db_obj=room, db_key=key).first()
    if existing:
        return existing

    interval = max(int(trigger_data.get("interval", 300)), 10)
    script = create_script(
        typeclass="typeclasses.scripts.RoomTriggerScript",
        key=key,
        obj=room,
        interval=interval,
        persistent=True,
        repeats=0,  # Infinite
        start_delay=True,
        attributes=[
            ("trigger_id", trigger_id),
            ("trigger_action", trigger_data.get("action")),
            ("trigger_parameters", dict(trigger_data.get("parameters") or {})),
        ],
    )
    if script is None:
        raise RuntimeError(f"Evennia refused to create timed trigger {trigger_id}")
    logger.info(f"Created timed trigger {trigger_id} on room {room.id} (interval: {interval}s)")
    return script


def create_timed_trigger(room, trigger_data: dict[str, Any]) -> Any | None:
    """
    Create a timed trigger script attached to a room.

    Like start_timed_trigger, but logs and returns None instead of raising.
    """
    try:
        return start_timed_trigger(room, trigger_data)
    except Exception as e:
        logger.exception(f"Failed to create timed trigger {trigger_data.get('id')}: {e}")
        return None


def delete_timed_triggers_for_room(room) -> int:
    """
    Delete all timed trigger scripts attached to a room.

    Args:
        room: The Evennia room object

    Returns:
        Number of scripts deleted
    """
    count = 0
    try:
        # Find scripts where obj is this room
        from evennia.scripts.models import ScriptDB

        scripts = ScriptDB.objects.filter(obj=room)

        for script in scripts:
            # Only delete our trigger scripts
            if hasattr(script, "db") and hasattr(script.db, "trigger_id") and script.db.trigger_id:
                script.stop()
                script.delete()
                count += 1

        if count > 0:
            logger.info(f"Deleted {count} timed triggers for room {room.id}")
        return count

    except Exception as e:
        logger.exception(f"Failed to delete timed triggers for room {room.id}: {e}")
        return count


def sync_timed_triggers_for_room(room) -> dict[str, Any]:
    """
    Synchronize timed triggers for a room based on room.db.triggers.

    Creates scripts for new timed triggers, deletes scripts for
    removed triggers, updates changed triggers.

    Args:
        room: The Evennia room object

    Returns:
        Dict with created, deleted, updated counts
    """
    results = {"created": 0, "deleted": 0, "updated": 0, "errors": []}

    try:
        triggers = room.db.triggers or []
        timed_trigger_ids = set()

        # Process current timed triggers
        for trigger in triggers:
            if trigger.get("type") != "timed":
                continue
            if not trigger.get("enabled", True):
                continue

            trigger_id = trigger.get("id")
            if not trigger_id:
                continue

            timed_trigger_ids.add(trigger_id)

            # Check if script exists
            from evennia.scripts.models import ScriptDB

            existing = ScriptDB.objects.filter(db_obj=room, db_key=f"trigger_{trigger_id}").exists()
            if not existing:
                # Create new script
                if create_timed_trigger(room, trigger):
                    results["created"] += 1
                else:
                    results["errors"].append(f"Failed to create {trigger_id}")

        # Find and delete orphaned scripts
        from evennia.scripts.models import ScriptDB

        existing_scripts = ScriptDB.objects.filter(obj=room)

        for script in existing_scripts:
            if (
                hasattr(script, "db")
                and hasattr(script.db, "trigger_id")
                and script.db.trigger_id
                and script.db.trigger_id not in timed_trigger_ids
            ):
                script.stop()
                script.delete()
                results["deleted"] += 1

        return results

    except Exception as e:
        logger.exception(f"Failed to sync timed triggers for room {room.id}: {e}")
        results["errors"].append(str(e))
        return results
