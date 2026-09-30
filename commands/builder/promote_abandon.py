"""
Builder commands for promoting and abandoning sandbox builds.
"""

from evennia.commands.command import Command
from evennia.utils.search import search_object
from django.utils import timezone


class CmdPromote(Command):
    """
    Promote a sandbox build to a live location.

    Usage:
        @promote <sandbox_dbref> = <destination>

    This moves all rooms from a builder sandbox to the specified
    destination container room.
    """

    key = "@promote"
    locks = "cmd:perm(Builder) or perm(Admin)"
    help_category = "Building"

    def func(self):
        if not self.args or "=" not in self.args:
            self.caller.msg("Usage: @promote <sandbox_dbref> = <destination>")
            return

        sandbox_ref, dest_ref = self.args.split("=", 1)
        sandbox_ref = sandbox_ref.strip()
        dest_ref = dest_ref.strip()

        # Find sandbox
        sandbox = search_object(sandbox_ref)
        if not sandbox:
            self.caller.msg(f"Could not find sandbox: {sandbox_ref}")
            return
        sandbox = sandbox[0]

        # Verify it's a sandbox
        if not sandbox.tags.has("web_builder"):
            self.caller.msg("That doesn't appear to be a builder sandbox.")
            return

        # Find destination
        dest = search_object(dest_ref)
        if not dest:
            self.caller.msg(f"Could not find destination: {dest_ref}")
            return
        dest = dest[0]

        # Move all contents
        moved_count = 0
        for obj in sandbox.contents:
            obj.move_to(dest, quiet=True)
            moved_count += 1

        # Delete empty sandbox
        sandbox_name = sandbox.key
        sandbox.delete()

        self.caller.msg(
            f"Promoted {moved_count} objects from '{sandbox_name}' to '{dest.key}'."
        )

        # Try to update Django project record
        try:
            from web.builder.models import BuildProject

            # Find project by sandbox tag
            project_tag = [t for t in sandbox.tags.all() if t.startswith("project_")]
            if project_tag:
                project_id = int(project_tag[0].replace("project_", ""))
                project = BuildProject.objects.get(pk=project_id)
                project.sandbox_room_id = None
                project.promoted_at = timezone.now()
                project.save()
        except Exception:
            pass  # Non-critical


class CmdAbandon(Command):
    """
    Abandon and delete a sandbox build.

    Usage:
        @abandon <sandbox_dbref>

    This deletes the sandbox and all rooms inside it.
    """

    key = "@abandon"
    locks = "cmd:perm(Builder) or perm(Admin)"
    help_category = "Building"

    def func(self):
        if not self.args:
            self.caller.msg("Usage: @abandon <sandbox_dbref>")
            return

        sandbox_ref = self.args.strip()

        # Find sandbox
        sandbox = search_object(sandbox_ref)
        if not sandbox:
            self.caller.msg(f"Could not find sandbox: {sandbox_ref}")
            return
        sandbox = sandbox[0]

        # Verify it's a sandbox
        if not sandbox.tags.has("web_builder"):
            self.caller.msg("That doesn't appear to be a builder sandbox.")
            return

        # Confirm
        sandbox_name = sandbox.key
        content_count = len(sandbox.contents)

        # Delete all contents recursively
        def delete_recursive(obj):
            for child in obj.contents:
                delete_recursive(child)
            obj.delete()

        for obj in list(sandbox.contents):
            delete_recursive(obj)

        sandbox.delete()

        self.caller.msg(
            f"Abandoned sandbox '{sandbox_name}' and deleted {content_count} objects."
        )

        # Try to update Django project record
        try:
            from web.builder.models import BuildProject

            project_tag = [t for t in sandbox.tags.all() if t.startswith("project_")]
            if project_tag:
                project_id = int(project_tag[0].replace("project_", ""))
                project = BuildProject.objects.get(pk=project_id)
                project.sandbox_room_id = None
                project.save()
        except Exception:
            pass  # Non-critical
