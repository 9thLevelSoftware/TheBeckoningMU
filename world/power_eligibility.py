"""Pure catalog eligibility shared by creation, advancement and legacy choices."""

from world.v5_data import DISCIPLINE_POWERS, find_power, resolve_trait


def power_requirement_errors(power_name, discipline_levels):
    """Catalog rating/amalgam failures, without reading or mutating a character."""
    power = find_power(power_name)
    if power is None:
        return (f"Unknown discipline power: {power_name}",)
    discipline, level = power["discipline"], power["level"]
    dots = discipline_levels.get(discipline, 0)
    errors = []
    if not dots:
        errors.append(f"{power['name']} is a {discipline} power and you have no {discipline}")
    elif level > dots:
        errors.append(f"{power['name']} needs {discipline} {level}; you have {dots}")
    if power.get("amalgam"):
        other, _, required = power["amalgam"].rpartition(" ")
        if discipline_levels.get(other, 0) < int(required):
            errors.append(f"{power['name']} also needs {power['amalgam']}")
    return tuple(errors)


def eligible_power_names(character, discipline_name, prospective_rating):
    """Unlearned powers permitted by the prospective dot and existing amalgams."""
    discipline = resolve_trait(discipline_name, "disciplines").name
    levels = dict(character.discipline_levels)
    levels[discipline] = prospective_rating
    known = {str(name).casefold() for name in character.known_powers}
    return tuple(
        power["name"]
        for power in DISCIPLINE_POWERS.values()
        if power["discipline"] == discipline
        and power["name"].casefold() not in known
        and not power_requirement_errors(power["name"], levels)
    )


def validate_power_choice(character, discipline_name, prospective_rating, power_name):
    """Return a canonical eligible choice, raising a player-facing ValueError."""
    discipline = resolve_trait(discipline_name, "disciplines").name
    power = find_power(power_name)
    if power is None:
        choices = eligible_power_names(character, discipline, prospective_rating)
        raise ValueError(f"Choose a {discipline} power: " + (", ".join(choices) or "none eligible"))
    if power["discipline"] != discipline:
        raise ValueError(f"{power['name']} is a {power['discipline']} power, not {discipline}")
    if power["name"].casefold() in {str(name).casefold() for name in character.known_powers}:
        raise ValueError(f"You already know {power['name']}")
    levels = dict(character.discipline_levels)
    levels[discipline] = prospective_rating
    errors = power_requirement_errors(power["name"], levels)
    if errors:
        raise ValueError("; ".join(errors))
    return power
