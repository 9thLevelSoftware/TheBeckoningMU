"""
Humanity System Utility Functions for V5

Handles Stains, Remorse rolls, Humanity tracking, Convictions, and Touchstones.
"""

from dice.dice_roller import roll_v5_pool


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


def add_stain(character, count=1):
    """
    Add Stains to character.

    Args:
        character: Character object
        count (int): Number of stains to add (default 1)

    Returns:
        dict: {
            'stains': new stain count,
            'message': narrative message
        }
    """
    character.stains = character.stains + count
    new_stains = character.stains

    stain_word = "Stain" if count == 1 else "Stains"

    if new_stains >= 10:
        message = (
            f"You gain {count} {stain_word}, bringing your total to {new_stains}. "
            f"Your conscience is heavily burdened. You MUST perform a Remorse roll soon."
        )
    elif new_stains >= 5:
        message = (
            f"You gain {count} {stain_word}, bringing your total to {new_stains}. "
            f"The weight of your transgressions grows heavy."
        )
    else:
        message = f"You gain {count} {stain_word}, bringing your total to {new_stains}."

    return {
        'stains': new_stains,
        'added': count,
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


def remorse_roll(character):
    """
    Perform Remorse roll (Humanity vs Stains).

    Mechanics:
    - Roll pool = current Humanity rating
    - Must get successes > current Stains to avoid Humanity loss
    - On failure: Lose 1 Humanity, clear all Stains
    - On success: Keep Humanity, clear all Stains

    Args:
        character: Character object

    Returns:
        dict: {
            'success': bool,
            'roll_result': RollResult object,
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
            'humanity_lost': False,
            'old_humanity': humanity,
            'new_humanity': humanity,
            'stains_cleared': 0,
            'message': "You have no Stains to roll Remorse for."
        }

    # Roll Humanity pool (no Hunger dice for Remorse rolls)
    result = roll_v5_pool(max(1, humanity), 0, 0)

    # Success if you get more successes than Stains
    success = result.total_successes > stains

    # Clear stains regardless of outcome
    stains_cleared = clear_stains(character)

    if success:
        message = (
            f"You roll {humanity} dice for Remorse and get {result.total_successes} successes. "
            f"This exceeds your {stains} Stains. You maintain your Humanity at {humanity}. "
            f"All Stains are cleared."
        )
        return {
            'success': True,
            'roll_result': result,
            'humanity_lost': False,
            'old_humanity': humanity,
            'new_humanity': humanity,
            'stains_cleared': stains_cleared,
            'message': message
        }
    else:
        # Lose 1 Humanity
        new_humanity = set_humanity(character, humanity - 1)
        message = (
            f"You roll {humanity} dice for Remorse and get {result.total_successes} successes. "
            f"This does not exceed your {stains} Stains. You lose 1 Humanity "
            f"(from {humanity} to {new_humanity}). All Stains are cleared. "
            f"The Beast draws closer."
        )
        return {
            'success': False,
            'roll_result': result,
            'humanity_lost': True,
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
    Add a Touchstone (mortal who anchors Humanity), through Character.add_touchstone.

    Max touchstones = current Humanity // 2

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
    humanity = character.humanity
    max_touchstones = humanity // 2

    if len(character.touchstones) >= max_touchstones:
        return {
            'success': False,
            'touchstones': character.touchstones,
            'message': (
                f"You can only have {max_touchstones} Touchstones "
                f"(Humanity {humanity} ÷ 2 = {max_touchstones}). "
                f"Remove one first or increase your Humanity."
            )
        }

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
            'touchstones': list,
            'max_touchstones': int
        }
    """
    humanity = get_humanity(character)

    return {
        'humanity': humanity,
        'stains': character.stains,
        'convictions': character.convictions,
        'touchstones': character.touchstones,
        'max_touchstones': humanity // 2
    }


def check_frenzy_risk(character, trigger_type):
    """
    Check if character is at risk of frenzy.

    Trigger types: 'hunger', 'fury', 'terror'

    Args:
        character: Character object
        trigger_type (str): Type of frenzy trigger

    Returns:
        dict: {
            'at_risk': bool,
            'difficulty': int,
            'trigger_type': str,
            'message': narrative message
        }
    """
    from .blood_utils import get_hunger
    from .clan_utils import get_clan

    hunger = get_hunger(character)
    humanity = get_humanity(character)
    clan = get_clan(character)

    # Base difficulty by trigger type
    if trigger_type == 'hunger':
        # Hunger frenzy triggered by seeing blood, Hunger 5, etc.
        base_diff = 2
        if hunger == 5:
            base_diff = 4  # Much harder to resist at Hunger 5
        message = "The scent of blood triggers your predatory instincts."
    elif trigger_type == 'fury':
        # Fury frenzy from provocation, humiliation
        base_diff = 3
        message = "Rage builds within you, threatening to consume your reason."
    elif trigger_type == 'terror':
        # Terror frenzy from fire, sunlight, True Faith
        base_diff = 3
        message = "Primal fear grips your undead heart."
    else:
        base_diff = 2
        message = f"You feel the Beast stirring ({trigger_type})."

    # Apply clan bane modifiers
    clan_modifier = 0
    if clan == "Brujah" and trigger_type == 'fury':
        clan_modifier = 2
        message += " |r(Brujah Bane: +2 difficulty to resist fury)|n"

    # Hunger increases difficulty
    hunger_modifier = hunger // 2
    difficulty = base_diff + hunger_modifier + clan_modifier

    return {
        'at_risk': True,
        'difficulty': difficulty,
        'trigger_type': trigger_type,
        'base_difficulty': base_diff,
        'hunger_modifier': hunger_modifier,
        'clan_modifier': clan_modifier,
        'message': message
    }


def resist_frenzy(character, difficulty):
    """
    Attempt to resist frenzy (Willpower + Composure vs Difficulty).

    Args:
        character: Character object
        difficulty (int): Difficulty of resistance roll

    Returns:
        dict: {
            'success': bool,
            'roll_result': RollResult object,
            'message': narrative message
        }
    """
    from .blood_utils import get_hunger

    # Get Willpower and Composure from the character
    willpower = character.current_willpower
    composure = character.get_trait("composure")

    pool = willpower + composure
    hunger = get_hunger(character)

    # Roll pool with Hunger dice
    result = roll_v5_pool(max(1, pool), hunger, difficulty)

    if result.is_success:
        message = (
            f"You roll {pool} dice (Willpower {willpower} + Composure {composure}) "
            f"with {hunger} Hunger dice and get {result.total_successes} successes "
            f"against difficulty {difficulty}. You resist the frenzy!"
        )
        if result.is_messy_critical:
            message += " However, the struggle was messy - you may have revealed your nature."

        return {
            'success': True,
            'roll_result': result,
            'message': message
        }
    else:
        message = (
            f"You roll {pool} dice (Willpower {willpower} + Composure {composure}) "
            f"with {hunger} Hunger dice and get {result.total_successes} successes "
            f"against difficulty {difficulty}. You FAIL to resist! "
            f"The Beast takes over..."
        )
        if result.is_bestial_failure:
            message += " A Bestial Failure - your frenzy is particularly savage!"

        return {
            'success': False,
            'roll_result': result,
            'message': message
        }
