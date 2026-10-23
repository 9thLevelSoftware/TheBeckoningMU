"""
Promotion engine for moving sandbox builds to live world.

This module handles the promotion of tested sandbox areas into the live game world,
creating connection exits and cleaning up the sandbox container.
"""

import logging
import threading
from typing import Any

from django.db import transaction
from django.utils import timezone
from evennia.objects.models import ObjectDB
from evennia.utils import search
from twisted.internet import reactor
from twisted.python.threadable import isInIOThread

logger = logging.getLogger(__name__)


def run_in_main_thread(callback):
    """Dispatch promotion using the caller's actual reactor-thread identity."""
    if isInIOThread():
        callback()
    elif reactor.running:
        reactor.callFromThread(callback)
    else:
        raise RuntimeError("The game reactor is not running; promotion was not started.")


# Direction opposites for bidirectional exit creation
DIRECTION_OPPOSITES = {
    "n": "s",
    "s": "n",
    "e": "w",
    "w": "e",
    "ne": "sw",
    "sw": "ne",
    "nw": "se",
    "se": "nw",
    "u": "d",
    "d": "u",
}


def _get_opposite_direction(direction: str) -> str | None:
    """
    Get the opposite direction for bidirectional exit creation.

    Args:
        direction: The direction string (n, s, e, w, ne, nw, se, sw, u, d)

    Returns:
        The opposite direction string, or None if direction is invalid
    """
    return DIRECTION_OPPOSITES.get(direction.lower())


def _do_promotion_in_main_thread(
    project_id: int, connection_room_id: int, connection_direction: str
) -> tuple[bool, dict[str, Any]]:
    """
    Actually perform promotion in Evennia's main thread.

    This function:
    1. Finds all rooms tagged with project_{project_id} and 'sandbox'
    2. Finds the connection room by dbref
    3. Validates no exit exists in the specified direction from connection room
    4. Removes 'sandbox' tag from all project rooms (moves them to live world)
    5. Creates exit from connection room to project's entry room
    6. Creates return exit from project entry room back to connection room

    Args:
        project_id: The BuildProject ID
        connection_room_id: The dbref of the live room to connect to
        connection_direction: Direction from live room into the build

    Returns:
        Tuple of (success: bool, result: dict)
        result contains: promoted_rooms, created_exits, entry_room_id, errors
    """
    try:
        from evennia.utils.create import create_object

        from web.builder.models import BuildProject

        errors = []

        # Find all project rooms with sandbox tag
        project_tag = f"project_{project_id}"
        sandbox_rooms = ObjectDB.objects.get_by_tag(key=[project_tag, "sandbox"]).filter(
            db_typeclass_path="typeclasses.rooms.Room"
        )
        container_id = BuildProject.objects.values_list("sandbox_room_id", flat=True).get(pk=project_id)
        sandbox_rooms = [room for room in sandbox_rooms if room.id != container_id]

        if not sandbox_rooms:
            return False, {"error": "No sandbox rooms found for this project"}

        # Find the connection room
        connection_room = None
        try:
            # Search by dbref (id)
            found = search.search_object(f"#{connection_room_id}")
            if found:
                connection_room = found[0]
        except Exception as e:
            logger.warning(f"Error searching for connection room #{connection_room_id}: {e}")

        if not connection_room:
            return False, {"error": f"Connection room #{connection_room_id} not found"}

        # Validate connection room is not a sandbox room
        if connection_room.tags.get("sandbox"):
            return False, {"error": "Cannot connect to another sandbox room"}

        # Check if exit already exists in that direction from connection room
        for exit_obj in connection_room.contents:
            if (
                hasattr(exit_obj, "destination")
                and exit_obj.destination
                and exit_obj.name.lower() == connection_direction.lower()
            ):
                return False, {"error": f"Exit '{connection_direction}' already exists from connection room"}

        # Determine entry room (room with lowest ID, or first in list)
        entry_room = min(sandbox_rooms, key=lambda r: r.id)

        # Create exit from connection room to project entry room
        created_exits = []
        try:
            forward_exit = create_object(
                typeclass="typeclasses.exits.Exit",
                key=connection_direction,
                aliases=[connection_direction.lower()],
                location=connection_room,
                destination=entry_room,
            )
            # Add tags to track this as a web builder exit
            forward_exit.tags.add("web_builder")
            forward_exit.tags.add(project_tag)
            created_exits.append(
                {
                    "id": forward_exit.id,
                    "name": forward_exit.name,
                    "source": connection_room.id,
                    "destination": entry_room.id,
                }
            )
            logger.info(f"Created exit from room {connection_room.id} to {entry_room.id} ({connection_direction})")
        except Exception as e:
            error_msg = f"Failed to create forward exit: {e}"
            logger.exception(error_msg)
            errors.append(error_msg)

        # Create return exit from project entry room back to connection room
        opposite_direction = _get_opposite_direction(connection_direction)
        if opposite_direction:
            try:
                return_exit = create_object(
                    typeclass="typeclasses.exits.Exit",
                    key=opposite_direction,
                    aliases=[opposite_direction.lower()],
                    location=entry_room,
                    destination=connection_room,
                )
                # Add tags to track this as a web builder exit
                return_exit.tags.add("web_builder")
                return_exit.tags.add(project_tag)
                created_exits.append(
                    {
                        "id": return_exit.id,
                        "name": return_exit.name,
                        "source": entry_room.id,
                        "destination": connection_room.id,
                    }
                )
                logger.info(
                    f"Created return exit from room {entry_room.id} to {connection_room.id} ({opposite_direction})"
                )
            except Exception as e:
                error_msg = f"Failed to create return exit: {e}"
                logger.exception(error_msg)
                errors.append(error_msg)

        # Only release sandbox tags after both connecting exits exist. On any
        # partial failure the project remains built, with its sandbox reference
        # and project tags available for staff reconciliation.
        promoted_count = 0
        if not errors:
            for obj in ObjectDB.objects.get_by_tag(key=[project_tag, "sandbox"]):
                if obj.id == container_id:
                    continue
                try:
                    obj.tags.remove("sandbox")
                    if obj in sandbox_rooms:
                        promoted_count += 1
                except Exception as e:
                    logger.warning(f"Failed to remove sandbox tag from object {obj.id}: {e}")
                    errors.append(f"Object {obj.id}: {e}")

        return not errors, {
            "promoted_rooms": promoted_count,
            "created_exits": created_exits,
            "entry_room_id": entry_room.id,
            "errors": errors if errors else None,
            **(
                {"error": "Promotion was incomplete; staff reconciliation is required.", "recovery_required": True}
                if errors
                else {}
            ),
        }

    except Exception as e:
        logger.exception(f"Promotion failed for project {project_id}")
        return False, {"error": str(e)}


def promote_project_to_live(
    project_id: int, connection_room_id: int, connection_direction: str
) -> tuple[bool, dict[str, Any]]:
    """
    Promote a built project from sandbox to live world.

    This function:
    1. Validates the project exists and is in 'built' status
    2. Validates the project has an active sandbox
    3. Calls _do_promotion_in_main_thread to move rooms and create exits
    4. On success: cleans up sandbox container, updates project status to 'live'

    Args:
        project_id: The BuildProject ID
        connection_room_id: The dbref of the live room to connect to
        connection_direction: Direction from live room into the build (n/s/e/w/etc)

    Returns:
        Tuple of (success: bool, result: dict)
        On success: result contains promoted_rooms, created_exits, entry_room_id
        On failure: result contains error message
    """
    from web.builder.models import BuildProject

    try:
        # Load and validate project
        try:
            project = BuildProject.objects.get(id=project_id)
        except BuildProject.DoesNotExist:
            return False, {"error": "Project not found"}

        # Validate project status
        if project.status != "built":
            return False, {"error": f"Project must be in 'built' status (current: {project.status})"}

        # Validate project has active sandbox
        if not project.sandbox_room_id:
            return False, {"error": "Project has no active sandbox"}

        # Validate direction
        if connection_direction.lower() not in DIRECTION_OPPOSITES:
            valid_directions = ", ".join(DIRECTION_OPPOSITES.keys())
            return False, {"error": f"Invalid direction '{connection_direction}'. Valid directions: {valid_directions}"}

        logger.info(
            f"Starting promotion for project {project_id}: "
            f"connecting to room #{connection_room_id} via {connection_direction}"
        )

        # Run promotion in main thread
        result = None
        error = None
        event = threading.Event()

        def wrapper():
            nonlocal result, error
            try:
                success, result = _do_promotion_in_main_thread(project_id, connection_room_id, connection_direction)
                if not success:
                    error = result.get("error") or "Promotion failed."
                    return
                if result.get("errors"):
                    result.update(
                        error="Promotion was incomplete; staff reconciliation is required.", recovery_required=True
                    )
                    error = result["error"]
                    return

                # Finalize in the game thread. Never call the broad sandbox
                # cleanup helper here: it deletes every project-tagged object,
                # including the area and connecting exits just promoted.
                with transaction.atomic():
                    project.refresh_from_db()
                    container_id = project.sandbox_room_id
                    project.mark_live()
                    containers = search.search_object(f"#{container_id}")
                    if not containers:
                        raise ValueError("Sandbox container disappeared; staff reconciliation is required.")
                    container = containers[0]
                    if (
                        container.id == result.get("entry_room_id")
                        or not container.tags.get(f"project_{project_id}")
                        or not container.tags.get("sandbox")
                    ):
                        raise ValueError("Sandbox container identity changed; staff reconciliation is required.")
                    container.delete()
                    project.promoted_at = timezone.now()
                    project.sandbox_room_id = None
                    project.save(update_fields=["promoted_at", "sandbox_room_id"])

                    from chronicle.services import record_event

                    payload = {"project_name": project.name} if project.is_public else {}
                    record_event(
                        idempotency_key=f"builder:{project.pk}:builder.promoted:{project.promoted_at.isoformat()}",
                        source_app="builder",
                        source_type="BuildProject",
                        source_id=str(project.pk),
                        kind="builder.promoted",
                        title="Builder project promoted",
                        summary="A builder project was promoted to the live world.",
                        payload=payload,
                        visibility="public" if project.is_public else "staff",
                        actor=project.user,
                        participants=(),
                        occurred_at=project.promoted_at,
                    )
            except Exception as e:
                error = str(e)
                result = {**(result or {}), "error": error, "recovery_required": True}
                logger.exception(f"Promotion wrapper error for project {project_id}")
            finally:
                event.set()

        run_in_main_thread(wrapper)
        if not event.wait(timeout=30):
            # _do_promotion can populate result before project finalization is
            # complete. The game-thread callback may still finish or fail;
            # never claim success from that intermediate result.
            return False, {
                "error": "Promotion completion is pending; staff must check the project before retrying.",
                "pending": True,
                "recovery_required": True,
            }

        if error:
            return False, {**(result or {}), "error": error}

        if not result:
            return False, {"error": "Promotion timed out"}

        # Promotion and project finalization both succeeded.
        logger.info(f"Promotion successful for project {project_id}: {result}")
        return True, result

    except Exception as e:
        logger.exception(f"Unexpected error promoting project {project_id}")
        return False, {"error": f"Unexpected error: {str(e)}"}
