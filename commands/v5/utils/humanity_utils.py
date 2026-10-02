"""
Humanity System Utility Functions for V5

Handles Stains, Remorse rolls, Humanity tracking, Convictions, and Touchstones.
"""

from dice.dice_roller import MAX_POOL, roll_v5_pool
from world.v5_data import BLOOD_POTENCY, FRENZY_PROVOCATIONS


def get_humanity(character):
    """
    Get character's current Humanity level.

    Args:
        character: Character object

    Returns:
        int: Humanity level (0-10)
    """
    return character.humanity


def set_humanity(character, value):
    """
    Set character's Humanity level, clamped to 0-10.

    Args:
        character: Character object
        value (int): New Humanity value

    Returns:
        int: Actual Humanity value set (after clamping)
    """
    character.humanity = value
    return character.humanity


def get_stains(character):
    """
    Get current Stain count.

    Args:
        character: Character object

    Returns:
        int: Stain count (0-10)
    """
    return character.stains


def stain_room(character):
    """Unmarked Humanity boxes that can still take a Stain: 10 - Humanity - Stains."""
    return max(0, 10 - character.humanity - character.stains)


def add_stain(character, count=1):
    """
    Add Stains to a character (QR p.3).

    Stains fill the Humanity tracker's unmarked boxes (10 - Humanity). A Stain
    that would overfill them is not stored; instead the character takes one
    Aggravated Willpower damage for each such Stain.

    Args:
        character: Character object
        count (int): Number of stains to add (default 1)

    Returns:
        dict: {
            'stains': new stain count,
            'added': Stains actually marked,
            'overflow': Stains that became Aggravated Willpower damage,
            'message': narrative message
        }
    """
    room = stain_room(character)
    marked = min(count, room)
    overflow = count - marked
    character.stains = character.stains + marked
    if overflow:
        willpower = character.damage["willpower"]
        character.set_damage("willpower", aggravated=willpower["aggravated"] + overflow)
    new_stains = character.stains

    stain_word = "Stain" if count == 1 else "Stains"
    message = f"You gain {count} {stain_word}, bringing your total to {new_stains}."
    if overflow:
        message += (
            f" Your Humanity tracker is full: {overflow} Stain{'s' if overflow != 1 else ''} "
            f"become{'s' if overflow == 1 else ''} Aggravated Willpower damage."
        )
    if new_stains:
        message += " Make a Remorse test at the end of the session (+remorse)."
    if character.degenerating:
        message += (
            " Your Humanity tracker is full: you are Impaired (Degeneration), -2 dice to all tests "
            "until your Remorse test."
        )

    return {
        'stains': new_stains,
        'added': marked,
        'overflow': overflow,
        'message': message
    }


def clear_stains(character):
    """
    Clear all Stains from character.

    Args:
        character: Character object

    Returns:
        int: Number of stains that were cleared
    """
    old_stains = character.stains
    character.stains = 0
    return old_stains


def remorse_pool(character):
    """Remorse dice: the unmarked Humanity boxes, 10 - Humanity - Stains, minimum 1 (QR p.3)."""
    return max(1, 10 - character.humanity - character.stains)


def remorse_roll(character):
    """
    Make the end-of-session Remorse test (QR p.3; core p.239).

    Roll one die per unmarked Humanity box (10 - Humanity - Stains, minimum
    1). Any success keeps Humanity; a failure loses 1 Humanity. Either way
    all Stains are cleared. Remorse is a Humanity test, so it uses no Hunger
    dice (and no Blood Surge).

    Returns:
        dict: {
            'success': bool,
            'roll_result': RollResult or None (no Stains),
            'pool': int,
            'humanity_lost': bool,
            'old_humanity': int,
            'new_humanity': int,
            'stains_cleared': int,
            'message': narrative message
        }
    """
    humanity = get_humanity(character)
    stains = get_stains(character)

    if stains == 0:
        return {
            'success': True,
            'roll_result': None,
            'pool': 0,
            'humanity_lost': False,
            'old_humanity': humanity,
            'new_humanity': humanity,
            'stains_cleared': 0,
            'message': "You have no Stains to roll Remorse for."
        }

    pool = remorse_pool(character)
    result = roll_v5_pool(pool, 0, 1)
    stains_cleared = clear_stains(character)
    dice_word = 'die' if pool == 1 else 'dice'

    if result.is_success:
        new_humanity = humanity
        message = (
            f"You roll {pool} {dice_word} for Remorse and get {result.total_successes} successes. "
            f"You keep your Humanity at {humanity}. All Stains are cleared."
        )
    else:
        new_humanity = set_humanity(character, humanity - 1)
        message = (
            f"You roll {pool} {dice_word} for Remorse and get no successes. "
            f"You lose 1 Humanity (from {humanity} to {new_humanity}). All Stains are cleared."
        )
    return {
        'success': result.is_success,
        'roll_result': result,
        'pool': pool,
        'humanity_lost': not result.is_success,
        'old_humanity': humanity,
        'new_humanity': new_humanity,
        'stains_cleared': stains_cleared,
        'message': message
    }


def lose_humanity(character, amount=1):
    """
    Decrease Humanity (min 0).

    Args:
        character: Character object
        amount (int): Amount to decrease (default 1)

    Returns:
        dict: {
            'old_humanity': int,
            'new_humanity': int,
            'message': narrative message
        }
    """
    old_humanity = get_humanity(character)
    new_humanity = set_humanity(character, old_humanity - amount)

    if new_humanity == 0:
        message = (
            f"Your Humanity drops from {old_humanity} to {new_humanity}. "
            f"You have lost all connection to your mortal life. The Beast has won."
        )
    elif new_humanity <= 2:
        message = (
            f"Your Humanity drops from {old_humanity} to {new_humanity}. "
            f"You are becoming more monster than person."
        )
    else:
        message = f"Your Humanity drops from {old_humanity} to {new_humanity}."

    return {
        'old_humanity': old_humanity,
        'new_humanity': new_humanity,
        'amount': amount,
        'message': message
    }


def gain_humanity(character, amount=1):
    """
    Increase Humanity (max 10). Very rare, requires significant RP.

    Args:
        character: Character object
        amount (int): Amount to increase (default 1)

    Returns:
        dict: {
            'old_humanity': int,
            'new_humanity': int,
            'message': narrative message
        }
    """
    old_humanity = get_humanity(character)
    new_humanity = set_humanity(character, old_humanity + amount)

    if new_humanity == 10:
        message = (
            f"Your Humanity rises from {old_humanity} to {new_humanity}. "
            f"You have achieved remarkable redemption."
        )
    elif new_humanity >= 8:
        message = (
            f"Your Humanity rises from {old_humanity} to {new_humanity}. "
            f"You cling tightly to your human nature."
        )
    else:
        message = f"Your Humanity rises from {old_humanity} to {new_humanity}."

    return {
        'old_humanity': old_humanity,
        'new_humanity': new_humanity,
        'amount': amount,
        'message': message
    }


def add_conviction(character, conviction_text):
    """
    Add a Conviction (max 3), through Character.add_conviction.

    Args:
        character: Character object
        conviction_text (str): The conviction statement

    Returns:
        dict: {
            'success': bool,
            'convictions': list of current convictions,
            'message': result message
        }
    """
    try:
        text = character.add_conviction(conviction_text)
    except ValueError as err:
        message = str(err)
        if "already have" in message:
            message = "You already have 3 Convictions (the maximum). Remove one first."
        return {'success': False, 'convictions': character.convictions, 'message': message}

    return {
        'success': True,
        'convictions': character.convictions,
        'message': f"Conviction added: {text}"
    }


def remove_conviction(character, index):
    """
    Remove a Conviction by index, through Character.remove_conviction.

    Args:
        character: Character object
        index (int): Index of conviction to remove (0-2)

    Returns:
        dict: {
            'success': bool,
            'convictions': list of current convictions,
            'message': result message
        }
    """
    try:
        removed = character.remove_conviction(index)
    except (IndexError, ValueError):
        return {
            'success': False,
            'convictions': character.convictions,
            'message': f"Invalid conviction index: {index}"
        }

    return {
        'success': True,
        'convictions': character.convictions,
        'message': f"Conviction removed: {removed}"
    }


def add_touchstone(character, name, description, conviction_index=0):
    """
    Add a Touchstone (a mortal who anchors Humanity), through Character.add_touchstone.

    The book ties each Touchstone to a Conviction (core p.172-173; one to
    three of each at creation); it sets no cap based on Humanity.

    Args:
        character: Character object
        name (str): Touchstone's name
        description (str): Touchstone description
        conviction_index (int): Which conviction they represent (0-2)

    Returns:
        dict: {
            'success': bool,
            'touchstones': list of current touchstones,
            'message': result message
        }
    """
    try:
        character.add_touchstone(name, description, conviction_index)
    except ValueError as err:
        return {'success': False, 'touchstones': character.touchstones, 'message': str(err)}

    return {
        'success': True,
        'touchstones': character.touchstones,
        'message': f"Touchstone added: {name} - {description}"
    }


def remove_touchstone(character, index):
    """
    Remove a Touchstone by index, through Character.remove_touchstone.

    Args:
        character: Character object
        index (int): Index of touchstone to remove

    Returns:
        dict: {
            'success': bool,
            'touchstones': list of current touchstones,
            'message': result message
        }
    """
    try:
        removed = character.remove_touchstone(index)
    except (IndexError, ValueError):
        return {
            'success': False,
            'touchstones': character.touchstones,
            'message': f"Invalid touchstone index: {index}"
        }

    return {
        'success': True,
        'touchstones': character.touchstones,
        'message': f"Touchstone removed: {removed['name']}"
    }


def get_humanity_status(character):
    """
    Get full Humanity status display.

    Args:
        character: Character object

    Returns:
        dict: {
            'humanity': int,
            'stains': int,
            'convictions': list,
            'touchstones': list
        }
    """
    humanity = get_humanity(character)

    return {
        'humanity': humanity,
        'stains': character.stains,
        'convictions': character.convictions,
        'touchstones': character.touchstones,
    }


def frenzy_provocations(frenzy_type):
    """The book's provocations and difficulties for a frenzy type (QR p.13).

    Returns the world.v5_data.FRENZY_PROVOCATIONS entry ({"goal",
    "provocations": {text: difficulty}}), or None for an unknown type.
    """
    return FRENZY_PROVOCATIONS.get(str(frenzy_type or "").strip().lower())


def frenzy_bane_penalty(character, frenzy_type):
    """Dice a clan bane takes off a frenzy test, and why ((0, None) if none).

    Brujah (Violent Temper, v5_data.CLANS): subtract Bane Severity dice
    (BLOOD_POTENCY[bp]["bane_severity"]) from rolls to resist fury frenzy.
    """
    if frenzy_type == "fury" and character.clan == "Brujah":
        severity = BLOOD_POTENCY.get(character.blood_potency, {}).get("bane_severity", 0)
        if severity:
            return severity, f"Brujah bane, Violent Temper: -{severity} dice"
    return 0, None


def frenzy_pool(character, frenzy_type=None):
    """The frenzy test pool (QR p.4): current Willpower + Humanity / 3 (rounded
    down), less any clan bane dice, minimum 1. Returns (pool, breakdown text)."""
    willpower = character.current_willpower
    third = character.humanity // 3
    penalty, bane_text = frenzy_bane_penalty(character, frenzy_type)
    breakdown = f"Willpower {willpower} + Humanity/3 {third}"
    if bane_text:
        breakdown += f" ({bane_text})"
    return max(1, willpower + third - penalty), breakdown


def resist_frenzy(character, difficulty, frenzy_type=None):
    """
    Test to resist frenzy (QR p.4): current Willpower + Humanity / 3 against
    the provocation's difficulty (QR p.13; v5_data.FRENZY_PROVOCATIONS).

    A frenzy test is a Willpower test, so it rolls no Hunger dice and takes
    no Blood Surge. `frenzy_type` ("fury", "hunger", "terror") applies clan
    banes such as the Brujah's.

    Returns:
        dict: {'success': bool, 'roll_result': RollResult, 'pool': int,
               'breakdown': str, 'difficulty': int, 'frenzy_type': str|None,
               'message': str}
    """
    pool, breakdown = frenzy_pool(character, frenzy_type)
    result = roll_v5_pool(min(MAX_POOL, pool), 0, difficulty)
    kind = f"{frenzy_type} " if frenzy_type else ""
    rolled = (
        f"You roll {pool} dice ({breakdown}) and get {result.total_successes} successes "
        f"against Difficulty {difficulty}."
    )
    if result.is_success:
        message = f"{rolled} You resist the {kind}frenzy."
    else:
        message = (
            f"{rolled} You fail: the Beast takes over ({kind}frenzy). The Storyteller runs your "
            "frenzy; you may spend Willpower to regain control."
        )
    return {
        'success': result.is_success,
        'roll_result': result,
        'pool': pool,
        'breakdown': breakdown,
        'difficulty': difficulty,
        'frenzy_type': frenzy_type,
        'message': message,
    }


def pending_frenzy_test(character):
    """The hunger frenzy test(s) the character owes, or None.

    Recorded by dice.rouse_checker.flag_hunger_frenzy when a Rouse would
    take Hunger past 5: {"type", "difficulty", "reason", "time", "count"}.
    """
    pending = character.db.pending_frenzy_test
    if not pending:
        return None
    return dict(pending)


def roll_pending_frenzy_tests(character):
    """Roll the owed hunger frenzy test(s) now and clear the record.

    One test per Rouse failure past Hunger 5, each at the recorded
    difficulty (4). Once a test fails the vampire is already in frenzy, so
    the remaining tests are not rolled. Returns a list of resist_frenzy
    results ([] if nothing was owed).
    """
    pending = pending_frenzy_test(character)
    if character.attributes.has("pending_frenzy_test"):
        character.attributes.remove("pending_frenzy_test")
    if not pending:
        return []
    results = []
    for _ in range(max(1, int(pending.get("count") or 1))):
        result = resist_frenzy(character, pending.get("difficulty", 4), pending.get("type", "hunger"))
        results.append(result)
        if not result["success"]:
            break
    return results


def format_frenzy_tests(results, reason=None):
    """Display lines for rolled hunger frenzy tests."""
    if not results:
        return []
    why = f" ({reason})" if reason else ""
    lines = [f"|r|hHunger frenzy test{why}: your Hunger can't rise past 5.|n"]
    for number, result in enumerate(results, 1):
        label = f"Test {number}: " if len(results) > 1 else ""
        lines.append(f"{label}{result['roll_result'].format_result(show_details=True)}")
        lines.append(result["message"])
    return lines
