"""Shared resolved-trait classification and labelled pool modifiers."""

from world.v5_data import UnknownTrait, resolve_trait


def resolve_pool_traits(trait_names):
    """Resolve available traits; unknown names keep their caller's error policy."""
    resolved = []
    for name in trait_names:
        try:
            resolved.append(resolve_trait(name))
        except UnknownTrait:
            continue
    return tuple(resolved)


def is_physical_pool(resolved_traits):
    """The hunting rule: a Physical Attribute makes the test Physical."""
    return any(ref.category == "attributes" and ref.group == "physical" for ref in resolved_traits)


def impairment_for_pool(character, resolved_traits):
    """Character.dice_penalty, with independently labelled applicable components."""
    physical = is_physical_pool(resolved_traits)
    if not hasattr(character, "dice_penalty"):
        return {"penalty": 0, "components": {}, "physical": physical}
    general = min(0, character.dice_penalty())
    penalty = min(0, character.dice_penalty(physical=physical))
    components = {}
    if general:
        components["Degeneration (Humanity tracker full)"] = general
    if penalty - general:
        components["Health impairment"] = penalty - general
    return {"penalty": penalty, "components": components, "physical": physical}


def effect_modifiers_for_pool(character, resolved_traits, *, context=None):
    """Fleetness applies to explicit noncombat Dexterity or one dodge per turn.

    This only quotes modifiers; choosing/rolling a defense consumes its use.
    """
    from commands.v5.utils.discipline_effects import active_power_bonus, fleetness_defense_used

    traits = {(ref.category, ref.key) for ref in resolved_traits}
    dexterity = ("attributes", "dexterity") in traits
    eligible = context == "noncombat" and dexterity
    if context == "defense":
        eligible = (
            traits == {("attributes", "dexterity"), ("skills", "athletics")}
            and len(resolved_traits) == 2
            and not fleetness_defense_used(character)
        )
    if not eligible:
        return {}
    bonus = active_power_bonus(character, "Fleetness", "dexterity_bonus")
    return {"Fleetness": bonus} if bonus else {}
