"""
Room

Rooms are simple containers that has no location of their own.

"""

from evennia.typeclasses.attributes import AttributeProperty
from evennia.objects.objects import DefaultRoom
from evennia.utils.ansi import ANSIString
from evennia.utils.evtable import EvTable
from .objects import ObjectParent

from web.builder.trigger_engine import execute_triggers


class Room(ObjectParent, DefaultRoom):
    """
    Rooms are like any Object, except their location is None
    (which is default). They also use basetype_setup() to
    add locks so they cannot be הם puppeted or picked up.
    (to change that, use at_object_creation instead)

    See examples/object.py for a list of
    properties and methods available on all Objects.
    """

    exits_per_row = AttributeProperty(3)

    # Styling for EvTables in the room display output
    styles = {
        "title": {
            "fill_char": ANSIString("|R=|n"),
        },
        # Common Section Styles
        "section_table": {
            "header_line_char": ANSIString("|R-|n"),
            "border": "header",
            "pad_left": 1,
            "pad_right": 1,
        },
        "section_header": {},
        "section_contents": {},
        # Character Section Styles
        "character_section_table": {
            "valign": "b",
        },
        "character_section_header": {},
        "character_section_contents": {
            "pad_top": 1,
        },
        "character_shortdesc_column": {},
        "character_idle_time_column": {
            "align": "r",
        },
        "character_name_column": {},
        # Exit Section Styles
        "exit_section_table": {
            "pad_top": 0,
            "pad_bottom": 0,
        },
        "exit_section_header": {},
        "exit_section_contents": {},
        "footer": {
            "fill_char": ANSIString("|R=|n"),
        },
    }

    def get_display_tag_mapping(self, looker, **kwargs):
        """
        Returns a mapping of Evennia tags that should be displayed next to the name of an object

        The keys are the names of the Evennia Tags that should be displayed.
        The values are the text to display when that tag is present on the object
        """
        return {"ooc": "OOC Area"}

    def get_display_desc(self, looker, **kwargs):
        """
        Returns the displayed description of the room
        """
        return self.db.desc or "You see nothing special."

    def get_display_characters(self, looker, **kwargs):
        """
        Returns a list of DefaultCharacters that should be displayed in the room for the given viewer.
        """
        characters = [
            char
            for char in self.contents
            if char.has_account and char.access(looker, "view")
        ]
        if not characters:
            return ""
        width = looker.get_min_client_width()
        table = EvTable(
            width=width,
            **{
                **self.styles["section_table"],
                **self.styles["character_section_table"],
            },
        )
        table.add_header(
            "|w Characters |n",
            **{
                **self.styles["section_header"],
                **self.styles["character_section_header"],
            },
        )
        for char in characters:
            name = char.get_display_name(looker, **kwargs)
            idle_time = char.format_idle_time(looker, **kwargs)
            shortdesc = char.get_display_shortdesc(looker, **kwargs)

            table.add_row(
                *[shortdesc, name, idle_time],
                **{
                    **self.styles["section_contents"],
                    **self.styles["character_section_contents"],
                },
            )
        table.reformat_column(0, **self.styles["character_shortdesc_column"])
        table.reformat_column(
            1, width=int(width * 0.25), **self.styles["character_name_column"]
        )
        table.reformat_column(
            2, width=int(width * 0.0625), **self.styles["character_idle_time_column"]
        )
        return ANSIString("\n").join(table.get())

    def get_display_exits(self, looker, **kwargs):
        """
        Returns a list of DefaultExits that should be displayed in the room for the given viewer.
        """
        exits = [exit for exit in self.contents if exit.destination]

        if not exits:
            return ""
        width = looker.get_min_client_width()
        table = EvTable(
            width=width,
            **{
                **self.styles["section_table"],
                **self.styles["exit_section_table"],
            },
        )
        table.add_header(
            " |wExits|n ",
            **{
                **self.styles["section_header"],
                **self.styles["exit_section_header"],
            },
        )
        exits = [
            exit.get_display_name(looker, **kwargs)
            for exit in sorted(exits, key=lambda e: e.name)
        ]
        for i in range(0, len(exits), self.exits_per_row):
            table.add_row(
                *exits[i : i + self.exits_per_row],
                **{
                    **self.styles["section_contents"],
                    **self.styles["exit_section_contents"],
                },
            )
        return ANSIString("\n").join(table.get())

    def get_display_header(self, looker, **kwargs):
        """
        Get the 'header' of the room description. Called by `return_appearance`.
        """
        # This method was missing from the previous `type` output for Room
        # But `return_appearance` calls it.
        # Based on the screenshot example: "===================================[ Limbo ]===================================="
        # Wait, `return_appearance` logic in the reference code I got:
        # title = ANSIString(f"|Y[|n {name} |Y]|n").center(looker.get_min_client_width(), self.styles["title"]["fill_char"])
        # So the "title" IS the header line in that implementation.
        # But `return_appearance` ALSO calls `header = self.get_display_header(looker, **kwargs)` separately.
        # If I look at the reference `type` output again...

        # Ah, I see. `return_appearance` calls:
        # header = self.get_display_header(looker, **kwargs)
        # title = ...
        # ...
        # return ANSIString("\n\n").join(s for s in [header, title, ...] if s)

        # If `get_display_header` was missing in the file I `type`d, maybe it's inherited?
        # But `ObjectParent` didn't have it. `DefaultRoom` doesn't have it.
        # Maybe I missed it in the output?
        # Or maybe the reference code relies on it returning None/Empty string by default if not present?
        # But if I call it and it doesn't exist -> AttributeError.

        # Let's check the `type` output for `rooms.py` again very carefully.
        # I scrolled up. I see `get_display_tag_mapping`. I see `get_display_desc`.
        # It seems `get_display_header` IS MISSING from the file content I got.

        # Wait, I might have just missed it or the `type` command truncated?
        # The output ends with `return_appearance`.
        # Let's assume `get_display_header` returns an empty string or similar if I can't find it.
        # Or maybe I should implement it to match the "top border" if the title isn't enough?
        # In the example:
        # ===================================[ Limbo ]====================================
        # This looks like the `title` variable in `return_appearance`.
        # So `header` might be something above it?
        # Or maybe `header` is just an empty hook for customization.

        # I will define `get_display_header` to return "" for now to avoid AttributeError.

        return ""

    def get_display_footer(self, looker, **kwargs):
        """
        Get the 'footer' of the room description. Called by `return_appearance`.
        """
        styles = self.styles["footer"]
        width = looker.get_min_client_width()
        return styles["fill_char"] * width

    def access(self, accessing_obj, access_type="view", default=False, **kwargs):
        """
        Override access to implement sandbox isolation.
        Sandbox rooms can only be entered by:
        - The builder who owns the sandbox
        - Staff members
        """
        if access_type == "traverse" and self.tags.get("sandbox"):
            # Check if accessing_obj is the sandbox owner
            # Sandbox rooms are tagged with project_{id}
            project_tags = [t for t in self.tags.all() if t.startswith("project_")]
            if project_tags:
                from web.builder.models import BuildProject

                try:
                    project_id = int(project_tags[0].split("_")[1])
                    project = BuildProject.objects.get(id=project_id)

                    # Allow if owner or staff
                    if (
                        hasattr(accessing_obj, "account")
                        and accessing_obj.account == project.user
                    ):
                        return True
                    if accessing_obj.check_permstring("Admin"):
                        return True

                    # Deny regular players
                    return False
                except (ValueError, BuildProject.DoesNotExist):
                    pass

        # Default access for non-sandbox or other access types
        return super().access(accessing_obj, access_type, default, **kwargs)

    def return_appearance(self, looker, **kwargs):
        """
        This is the hook for returning the appearance of the room.
        """
        header = self.get_display_header(looker, **kwargs)

        name = self.get_display_name(looker, **kwargs)

        title = ANSIString(f"|Y[|n {name} |Y]|n").center(
            looker.get_min_client_width(), self.styles["title"]["fill_char"]
        )

        desc = self.get_display_desc(looker, **kwargs)

        character_section = self.get_display_characters(looker, **kwargs)

        exit_section = self.get_display_exits(looker, **kwargs)

        footer = self.get_display_footer(looker, **kwargs)

        return ANSIString("\n\n").join(
            s
            for s in [header, title, desc, character_section, exit_section, footer]
            if s
        )

    def at_object_receive(self, moved_obj, source_location, move_type="move", **kwargs):
        """
        Hook called when an object enters this room.
        Triggers entry triggers for player characters.
        """
        # Call parent first to preserve default behavior
        super().at_object_receive(
            moved_obj, source_location, move_type=move_type, **kwargs
        )

        # Only trigger for characters with accounts (player characters, not NPCs)
        if hasattr(moved_obj, "has_account") and moved_obj.has_account:
            try:
                execute_triggers(self, "entry", moved_obj)
            except Exception as e:
                # Log error but don't crash the room
                import logging

                logger = logging.getLogger(__name__)
                logger.exception(f"Error executing entry triggers in {self}: {e}")

    def at_object_leave(self, moved_obj, target_location, move_type="move", **kwargs):
        """
        Hook called when an object leaves this room.
        Triggers exit triggers for player characters.
        """
        # Only trigger for characters with accounts (player characters, not NPCs)
        if hasattr(moved_obj, "has_account") and moved_obj.has_account:
            try:
                execute_triggers(
                    self, "exit", moved_obj, target_location=target_location
                )
            except Exception as e:
                # Log error but don't crash the room
                import logging

                logger = logging.getLogger(__name__)
                logger.exception(f"Error executing exit triggers in {self}: {e}")

        # Call parent after trigger execution
        super().at_object_leave(
            moved_obj, target_location, move_type=move_type, **kwargs
        )
