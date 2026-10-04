"""
Promotion engine for moving sandbox builds to live world.

This module handles the promotion of tested sandbox areas into the live game world,
creating connection exits and cleaning up the sandbox container.
"""

import logging
import threading
from typing import Any, Dict, Optional, Tuple

from evennia.utils import search
from evennia.utils.utils import run_in_main_thread

logger = logging.getLogger(__name__)

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


def _get_opposite_direction(direction: str) -> Optional[str]:
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
) -> Tuple[bool, Dict[str, Any]]:
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

        from typeclasses.exits import Exit
        from typeclasses.rooms import Room

        errors = []

        # Find all project rooms with sandbox tag
        project_tag = f"project_{project_id}"
        sandbox_rooms = search.search_object(
            "",
            typeclass="typeclasses.rooms.Room",
            tags=[project_tag, "sandbox"],
        )

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
            logger.warning(
                f"Error searching for connection room #{connection_room_id}: {e}"
            )

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
                return False, {
                    "error": f"Exit '{connection_direction}' already exists from connection room"
                }

        # Determine entry room (room with lowest ID, or first in list)
        entry_room = min(sandbox_rooms, key=lambda r: r.id)

        # Remove 'sandbox' tag from all project rooms (moves them to live world)
        promoted_count = 0
        for room in sandbox_rooms:
            try:
                room.tags.remove("sandbox")
                promoted_count += 1
            except Exception as e:
                logger.warning(f"Failed to remove sandbox tag from room {room.id}: {e}")
                errors.append(f"Room {room.id}: {e}")

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
            logger.info(
                f"Created exit from room {connection_room.id} to {entry_room.id} "
                f"({connection_direction})"
            )
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
                    f"Created return exit from room {entry_room.id} to {connection_room.id} "
                    f"({opposite_direction})"
                )
            except Exception as e:
                error_msg = f"Failed to create return exit: {e}"
                logger.exception(error_msg)
                errors.append(error_msg)

        return True, {
            "promoted_rooms": promoted_count,
            "created_exits": created_exits,
            "entry_room_id": entry_room.id,
            "errors": errors if errors else None,
        }

    except Exception as e:
        logger.exception(f"Promotion failed for project {project_id}")
        return False, {"error": str(e)}


def promote_project_to_live(
    project_id: int, connection_room_id: int, connection_direction: str
) -> Tuple[bool, Dict[str, Any]]:
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
    from django.utils import timezone

    from web.builder.models import BuildProject
    from web.builder.sandbox_cleanup import cleanup_sandbox_for_project

    try:
        # Load and validate project
        try:
            project = BuildProject.objects.get(id=project_id)
        except BuildProject.DoesNotExist:
            return False, {"error": "Project not found"}

        # Validate project status
        if project.status != "built":
            return False, {
                "error": f"Project must be in 'built' status (current: {project.status})"
            }

        # Validate project has active sandbox
        if not project.sandbox_room_id:
            return False, {"error": "Project has no active sandbox"}

        # Validate direction
        if connection_direction.lower() not in DIRECTION_OPPOSITES:
            valid_directions = ", ".join(DIRECTION_OPPOSITES.keys())
            return False, {
                "error": f"Invalid direction '{connection_direction}'. "
                f"Valid directions: {valid_directions}"
            }

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
                success, result = _do_promotion_in_main_thread(
                    project_id, connection_room_id, connection_direction
                )
                if not success:
                    error = result.get("error")
            except Exception as e:
                error = str(e)
                logger.exception(f"Promotion wrapper error for project {project_id}")
            finally:
                event.set()

        run_in_main_thread(wrapper)
        event.wait(timeout=30)

        if error:
            return False, {"error": error}

        if not result:
            return False, {"error": "Promotion timed out"}

        # Promotion succeeded - clean up and update project
        logger.info(f"Promotion successful for project {project_id}: {result}")

        # Clean up the sandbox container room
        cleanup_success, cleanup_result = cleanup_sandbox_for_project(project_id)
        if not cleanup_success:
            logger.warning(
                f"Sandbox cleanup failed after promotion for project {project_id}: "
                f"{cleanup_result.get('error', 'Unknown error')}"
            )
            # Don't fail the promotion if cleanup fails - rooms are already live

        # Update project status to live
        transition_succeeded = False
        try:
            project.mark_live()
            transition_succeeded = True
        except ValueError as e:
            logger.error(f"Failed to mark project {project_id} as live: {e}")
            # Don't fail - promotion succeeded even if status update failed

        # Update promotion timestamp and clear sandbox reference
        project.promoted_at = timezone.now()
        project.sandbox_room_id = None
        project.save(update_fields=["promoted_at", "sandbox_room_id"])

        if transition_succeeded and not result.get("errors"):
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

        return True, result

    except Exception as e:
        logger.exception(f"Unexpected error promoting project {project_id}")
        return False, {"error": f"Unexpected error: {str(e)}"}
