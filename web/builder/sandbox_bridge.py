"""
Web-side entry point for the sandbox build.

Django worker threads hand the operation to the reactor and await its terminal
Deferred through blockingCallFromThread. Direct reactor callers receive a
Deferred for the final (success, result) pair. The synchronous unit adapter is
retained for isolated test runners without an active reactor.
"""

import logging
from typing import Any

from web.main_thread import call_in_main_thread

from .operation_runtime import OperationError
from .sandbox_builder import BuildError, build_deferred, build_unit

logger = logging.getLogger(__name__)


def create_sandbox_from_project(project_id: int, actor=None, expected_version=None) -> tuple[bool, dict[str, Any]]:
    """
    Build an approved project's snapshot as a sandbox.

    Returns:
        (True, {"sandbox_room_id", "room_count", "exit_count", ...}) on
        success, (False, {"error": message}) otherwise. On failure nothing
        the build created is left behind (the unit undoes itself).
    """
    try:
        from twisted.internet import defer, reactor

        if actor is None and not reactor.running:
            # Compatibility adapter for direct synchronous unit callers.
            return True, call_in_main_thread(build_unit, project_id)
        from .live_replacement import _require_actor
        from .models import BuildProject

        project = BuildProject.objects.get(pk=project_id)
        if actor is None:
            actor, expected_version = project.user, project.version
        if not reactor.running:
            _require_actor(project, actor)
            if project.version != expected_version:
                raise BuildError("Reviewed project version changed", status=409)
            return True, call_in_main_thread(build_unit, project_id)
        # blockingCallFromThread awaits a returned Deferred's terminal result.
        result = call_in_main_thread(build_deferred, project_id, actor, expected_version)
        if isinstance(result, defer.Deferred):
            # A direct reactor caller must await the pair, not receive early
            # success while its result is still a Deferred.
            result.addCallbacks(
                lambda value: (True, value),
                lambda failure: (False, {"error": str(failure.value), "status": getattr(failure.value, "status", 500)}),
            )
            return result
        return True, result
    except (BuildError, OperationError) as e:
        return False, {"error": str(e), "status": e.status}
    except Exception as e:
        logger.exception("Sandbox build failed for project %s", project_id)
        return False, {"error": f"Sandbox build failed: {e}", "status": 500}
