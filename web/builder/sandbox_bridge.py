"""
Thread-safe bridge for Django-to-Evennia communication.

This module provides a safe way to call Evennia APIs from Django web context
using run_in_main_thread() to ensure proper synchronization with the game loop.
"""

import logging
import threading
from typing import Any, Callable, Tuple, Dict, Optional

from django.core.exceptions import ObjectDoesNotExist

from evennia.utils.utils import run_in_main_thread

from .models import BuildProject
from .sandbox_builder import build_sandbox_area

logger = logging.getLogger(__name__)


def run_sync_in_main_thread(func: Callable, *args, **kwargs) -> Any:
    """
    Run a function in Evennia's main thread and block for result.

    This wrapper ensures thread-safe execution of Evennia API calls from
    the Django web thread. It uses a threading.Event to block until the
    main thread completes the operation.

    Args:
        func: The function to execute in the main thread
        *args: Positional arguments to pass to func
        **kwargs: Keyword arguments to pass to func

    Returns:
        The result of func(*args, **kwargs)

    Raises:
        Exception: Any exception raised by func is re-raised in the calling thread
        TimeoutError: If the operation takes longer than 30 seconds
    """
    result = None
    error = None
    event = threading.Event()

    def wrapper():
        nonlocal result, error
        try:
            result = func(*args, **kwargs)
        except Exception as e:
            error = e
            logger.exception("Error in main thread execution")
        finally:
            event.set()

    run_in_main_thread(wrapper)
    event.wait(timeout=30)  # 30 second timeout

    if error:
        raise error
    if not event.is_set():
        raise TimeoutError("Main thread execution timed out after 30 seconds")
    return result


def create_sandbox_from_project(project_id: int) -> Tuple[bool, Dict[str, Any]]:
    """
    Create a sandbox area from an approved BuildProject.

    This function:
    1. Loads the BuildProject from the database
    2. Validates the project is in 'approved' status
    3. Calls build_sandbox_area in the main thread to create rooms/exits
       from the approval snapshot (approved_map_data), not map_data
    4. Updates the project with the sandbox_room_id on success
    5. Transitions project status to 'built'

    Args:
        project_id: The ID of the BuildProject to build

    Returns:
        Tuple of (success: bool, result: dict)
        On success: result contains sandbox_room_id, room_count, exit_count, room_map
        On failure: result contains error message
    """
    try:
        # Load the project
        try:
            project = BuildProject.objects.get(pk=project_id)
        except ObjectDoesNotExist:
            return False, {"error": f"Project {project_id} not found"}

        # Validate status
        if project.status != "approved":
            return False, {
                "error": f"Project must be approved (current status: {project.status})"
            }

        # Check if already built
        if project.sandbox_room_id:
            return False, {
                "error": "Sandbox already exists",
                "sandbox_id": project.sandbox_room_id,
            }

        # Build only what was reviewed: the snapshot taken at approval, never
        # the live map_data.
        snapshot = project.approved_map_data or {}
        map_data = snapshot.get("map_data")
        if not map_data:
            return False, {"error": "Project has no approved snapshot to build"}
        if not map_data.get("rooms"):
            return False, {"error": "Project has no rooms to build"}

        logger.info(f"Starting sandbox build for project {project_id}: {project.name}")

        # Build sandbox in main thread
        try:
            build_result = run_sync_in_main_thread(
                build_sandbox_area, project_id, map_data
            )
        except Exception as e:
            logger.exception(f"Sandbox build failed for project {project_id}")
            return False, {"error": f"Sandbox build failed: {str(e)}"}

        # Update project with sandbox info
        project.sandbox_room_id = build_result["sandbox_room_id"]
        project.save(update_fields=["sandbox_room_id"])

        # Transition to built status
        try:
            project.mark_built()
        except ValueError as e:
            # This shouldn't happen since we checked status, but handle it
            logger.error(f"Failed to mark project {project_id} as built: {e}")
            # Don't fail the whole operation - sandbox was created successfully

        logger.info(
            f"Sandbox build complete for project {project_id}: "
            f"{build_result['room_count']} rooms, "
            f"{build_result['exit_count']} exits"
        )

        return True, build_result

    except Exception as e:
        logger.exception(f"Unexpected error creating sandbox for project {project_id}")
        return False, {"error": f"Unexpected error: {str(e)}"}
