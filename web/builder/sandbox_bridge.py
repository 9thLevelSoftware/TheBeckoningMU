"""
Web-side entry point for the sandbox build.

Django views run in a worker thread, outside the game loop. The build is one
unit of work (`sandbox_builder.build_unit`) that runs wholly on the reactor;
this module hands it over with `web.main_thread.call_in_main_thread` and
turns its outcome into the `(success, result)` pair the views return.
"""

import logging
from typing import Any

from web.main_thread import call_in_main_thread

from .sandbox_builder import BuildError, build_unit

logger = logging.getLogger(__name__)


def create_sandbox_from_project(project_id: int) -> tuple[bool, dict[str, Any]]:
    """
    Build an approved project's snapshot as a sandbox.

    Returns:
        (True, {"sandbox_room_id", "room_count", "exit_count", ...}) on
        success, (False, {"error": message}) otherwise. On failure nothing
        the build created is left behind (the unit undoes itself).
    """
    try:
        return True, call_in_main_thread(build_unit, project_id)
    except BuildError as e:
        return False, {"error": str(e), "status": e.status}
    except Exception as e:
        logger.exception("Sandbox build failed for project %s", project_id)
        return False, {"error": f"Sandbox build failed: {e}", "status": 500}
