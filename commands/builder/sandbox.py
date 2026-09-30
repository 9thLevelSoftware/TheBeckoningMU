"""
Sandbox commands for builder navigation and management.

Commands:
- @goto_sandbox: Teleport to your sandbox
- @list_sandboxes: Staff command to list all active sandboxes
- @cleanup_sandbox: Delete sandbox rooms and reset project status
"""

from evennia.commands.command import Command
from evennia.utils import search


class CmdGotoSandbox(Command):
    """
    Teleport to your sandbox entry room.

    Usage:
        @goto_sandbox
        @goto_sandbox <project_id>
        @gsb

    Without arguments, lists your active sandboxes.
    With a project ID, teleports you to that sandbox.
    """

    key = "@goto_sandbox"
    aliases = ["@gsb"]
    locks = "cmd:perm(Builder)"
    help_category = "Building"

    def func(self):
        from web.builder.models import BuildProject

        if not self.args:
            # List user's sandboxes
            projects = BuildProject.objects.filter(
                user=self.caller.account, sandbox_room_id__isnull=False
            )
            if not projects:
                self.caller.msg("You have no active sandboxes.")
                return

            msg = "Your sandboxes:|/"
            for p in projects:
                msg += f"  {p.name} (ID: {p.id})|/"
            msg += "|/Usage: @goto_sandbox <project_id>"
            self.caller.msg(msg)
            return

        try:
            project_id = int(self.args.strip())
            project = BuildProject.objects.get(
                id=project_id, user=self.caller.account, sandbox_room_id__isnull=False
            )
        except (ValueError, BuildProject.DoesNotExist):
            self.caller.msg("Sandbox not found or you don't have access.")
            return

        # Find the sandbox entry room using the project tag
        project_tag = f"project_{project.id}"
        rooms = search.search_object(
            "", typeclass="typeclasses.rooms.Room", tags=[project_tag]
        )
        if rooms:
            self.caller.move_to(rooms[0])
            self.caller.msg(f"Teleported to sandbox: {project.name}")
        else:
            self.caller.msg("Sandbox rooms not found. May need cleanup.")


class CmdListSandboxes(Command):
    """
    List all active sandboxes (staff only).

    Usage:
        @list_sandboxes
        @lsb

    Shows all projects with active sandboxes.
    """

    key = "@list_sandboxes"
    aliases = ["@lsb"]
    locks = "cmd:perm(Admin)"
    help_category = "Admin"

    def func(self):
        from web.builder.models import BuildProject

        projects = BuildProject.objects.filter(
            sandbox_room_id__isnull=False
        ).select_related("user")

        if not projects:
            self.caller.msg("No active sandboxes.")
            return

        msg = "Active sandboxes:|/"
        msg += "-" * 50 + "|/"
        for p in projects:
            msg += f"ID: {p.id} | {p.name} | Builder: {p.user.username}|/"
        self.caller.msg(msg)


class CmdCleanupSandbox(Command):
    """
    Clean up a sandbox by deleting all rooms/exits.

    Usage:
        @cleanup_sandbox <project_id>
        @csb <project_id>

    Deletes all sandbox rooms and exits for the specified project.
    Resets the project status to 'approved'.
    Only the builder who owns the sandbox or staff can cleanup.
    """

    key = "@cleanup_sandbox"
    aliases = ["@csb"]
    locks = "cmd:perm(Builder)"
    help_category = "Building"

    def func(self):
        from web.builder.models import BuildProject

        if not self.args:
            self.caller.msg("Usage: @cleanup_sandbox <project_id>")
            return

        try:
            project_id = int(self.args.strip())
            project = BuildProject.objects.get(id=project_id)
        except (ValueError, BuildProject.DoesNotExist):
            self.caller.msg("Project not found.")
            return

        # Permission check: staff or owner
        if not (
            self.caller.check_permstring("Admin") or project.user == self.caller.account
        ):
            self.caller.msg("You don't have permission to cleanup this sandbox.")
            return

        if not project.sandbox_room_id:
            self.caller.msg("This project has no active sandbox.")
            return

        # Import and call cleanup
        from web.builder.sandbox_cleanup import cleanup_sandbox_for_project

        success, result = cleanup_sandbox_for_project(project_id)

        if success:
            self.caller.msg(
                f"Sandbox cleaned: {result['deleted_rooms']} rooms, "
                f"{result['deleted_exits']} exits deleted."
            )
        else:
            self.caller.msg(f"Cleanup failed: {result.get('error', 'Unknown error')}")
