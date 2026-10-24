"""
Exits

Exits are connectors between Rooms. An exit always has a destination property
set and has a single command defined on itself with the same name as its key,
for allowing Characters to traverse the exit to its destination.

"""

from evennia.objects.objects import DefaultExit

from .objects import ObjectParent


class Exit(ObjectParent, DefaultExit):
    """
    Exits are connectors between rooms. Exits are normal Objects except
    they defines the `destination` property and overrides some hooks
    and methods to represent the exits.

    See mygame/typeclasses/objects.py for a list of
    properties and methods available on all Objects child classes like this.

    """

    def at_traverse(self, traversing_object, target_location, **kwargs):
        from web.builder.operation_runtime import OperationError, assert_mutation_allowed
        from world.room_rules import room_access

        try:
            assert_mutation_allowed(self, target_ids=(traversing_object, self.location, target_location))
        except OperationError as error:
            traversing_object.msg(str(error))
            return False
        if not self.access(traversing_object, "traverse") or (
            target_location is not None and not target_location.access(traversing_object, "traverse", default=True)
        ):
            self.at_failed_traverse(traversing_object)
            return False
        allowed, reason = room_access(traversing_object, target_location)
        if not allowed:
            traversing_object.msg(reason)
            return False
        return super().at_traverse(traversing_object, target_location, **kwargs)
