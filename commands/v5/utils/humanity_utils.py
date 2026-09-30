"""
Humanity System Utility Functions for V5

Handles Stains, Remorse rolls, Humanity tracking, Convictions, and Touchstones.
"""

from world.v5_dice import roll_pool, format_dice_result


def get_humanity(character):
    """
    Get character's current Humanity level.

    Args:
        character: Character object

    Returns:
        int: Humanity level (0-10)
    """
    vampire = character.db.vampire
    if not vampire:
        return 7  # Default humanity for non-vampires
    return vampire.get("humanity", 7)


def set_humanity(character, value):
    """
    Set character's Humanity level, clamped to 0-10.

    Args:
        character: Character object
        value (int): New Humanity value

    Returns:
        int: Actual Humanity value set (after clamping)
    """
    value = max(0, min(10, value))
    character.db.vampire["humanity"] = value
    return value


def get_humanity_data(character):
    """
    Get humanity_data dict, ensuring it exists.

    Args:
        character: Character object

    Returns:
        dict: humanity_data with convictions, touchstones, stains
    """
    if not hasattr(character.db, 'humanity_data') or not character.db.humanity_data:
        character.db.humanity_data = {
            'convictions': [],
            'touchstones': [],
            'stains': 0
        }
    return character.db.humanity_data


def get_stains(character):
    """
    Get current Stain count.

    Args:
        character: Character object

    Returns:
        int: Stain count (0-10)
    """
    hum_data = get_humanity_data(character)
    return hum_data.get('stains', 0)


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
    hum_data = get_humanity_data(character)
    old_stains = hum_data.get('stains', 0)
    new_stains = min(10, old_stains + count)
    hum_data['stains'] = new_stains

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
    hum_data = get_humanity_data(character)
    old_stains = hum_data.get('stains', 0)
    hum_data['stains'] = 0
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
            'roll_result': DiceResult object,
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
    result = roll_pool(humanity, difficulty=0, hunger=0)

    # Success if you get more successes than Stains
    success = result.successes > stains

    # Clear stains regardless of outcome
    stains_cleared = clear_stains(character)

    if success:
        message = (
            f"You roll {humanity} dice for Remorse and get {result.successes} successes. "
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
            f"You roll {humanity} dice for Remorse and get {result.successes} successes. "
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
    Add a Conviction (max 3).

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
    hum_data = get_humanity_data(character)
    convictions = hum_data.get('convictions', [])

    if len(convictions) >= 3:
        return {
            'success': False,
            'convictions': convictions,
            'message': "You already have 3 Convictions (the maximum). Remove one first."
        }

    convictions.append(conviction_text)
    hum_data['convictions'] = convictions

    return {
        'success': True,
        'convictions': convictions,
        'message': f"Conviction added: {conviction_text}"
    }


def remove_conviction(character, index):
    """
    Remove a Conviction by index.

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
    hum_data = get_humanity_data(character)
    convictions = hum_data.get('convictions', [])

    if index < 0 or index >= len(convictions):
        return {
            'success': False,
            'convictions': convictions,
            'message': f"Invalid conviction index: {index}"
        }

    removed = convictions.pop(index)
    hum_data['convictions'] = convictions

    return {
        'success': True,
        'convictions': convictions,
        'message': f"Conviction removed: {removed}"
    }


def add_touchstone(character, name, description, conviction_index=0):
    """
    Add a Touchstone (mortal who anchors Humanity).

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
    hum_data = get_humanity_data(character)
    touchstones = hum_data.get('touchstones', [])
    humanity = get_humanity(character)
    max_touchstones = humanity // 2

    if len(touchstones) >= max_touchstones:
        return {
            'success': False,
            'touchstones': touchstones,
            'message': (
                f"You can only have {max_touchstones} Touchstones "
                f"(Humanity {humanity} ÷ 2 = {max_touchstones}). "
                f"Remove one first or increase your Humanity."
            )
        }

    touchstone = {
        'name': name,
        'description': description,
        'conviction_index': conviction_index
    }
    touchstones.append(touchstone)
    hum_data['touchstones'] = touchstones

    return {
        'success': True,
        'touchstones': touchstones,
        'message': f"Touchstone added: {name} - {description}"
    }


def remove_touchstone(character, index):
    """
    Remove a Touchstone by index.

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
    hum_data = get_humanity_data(character)
    touchstones = hum_data.get('touchstones', [])

    if index < 0 or index >= len(touchstones):
        return {
            'success': False,
            'touchstones': touchstones,
            'message': f"Invalid touchstone index: {index}"
        }

    removed = touchstones.pop(index)
    hum_data['touchstones'] = touchstones

    return {
        'success': True,
        'touchstones': touchstones,
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
    hum_data = get_humanity_data(character)
    humanity = get_humanity(character)

    return {
        'humanity': humanity,
        'stains': hum_data.get('stains', 0),
        'convictions': hum_data.get('convictions', []),
        'touchstones': hum_data.get('touchstones', []),
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
            'roll_result': DiceResult object,
            'message': narrative message
        }
    """
    from .blood_utils import get_hunger

    # Get Willpower and Composure from character stats
    stats = character.db.stats if hasattr(character.db, 'stats') else {}
    willpower = stats.get('willpower', {}).get('permanent', 5)
    composure = stats.get('attributes', {}).get('composure', 2)

    pool = willpower + composure
    hunger = get_hunger(character)

    # Roll pool with Hunger dice
    result = roll_pool(pool, difficulty=difficulty, hunger=hunger)

    if result.is_success():
        message = (
            f"You roll {pool} dice (Willpower {willpower} + Composure {composure}) "
            f"with {hunger} Hunger dice and get {result.successes} successes "
            f"against difficulty {difficulty}. You resist the frenzy!"
        )
        if result.is_messy:
            message += " However, the struggle was messy - you may have revealed your nature."

        return {
            'success': True,
            'roll_result': result,
            'message': message
        }
    else:
        message = (
            f"You roll {pool} dice (Willpower {willpower} + Composure {composure}) "
            f"with {hunger} Hunger dice and get {result.successes} successes "
            f"against difficulty {difficulty}. You FAIL to resist! "
            f"The Beast takes over..."
        )
        if result.is_bestial:
            message += " A Bestial Failure - your frenzy is particularly savage!"

        return {
            'success': False,
            'roll_result': result,
            'message': message
        }
