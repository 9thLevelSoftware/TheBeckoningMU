"""
Status System Utility Functions

Helper functions for managing Status, calculating bonuses, and handling positions.
"""

from .models import CharacterStatus, CamarillaPosition, StatusRequest


def get_or_create_character_status(character):
    """
    Get or create CharacterStatus for a character.

    Args:
        character: Character object

    Returns:
        CharacterStatus: Character's status record
    """
    char_status, created = CharacterStatus.objects.get_or_create(
        character=character,
        defaults={
            'earned_status': 0,
            'position_status': 0,
            'temporary_status': 0,
            'sect': 'Camarilla',
            'reputation': ''
        }
    )

    return char_status


def get_character_status(character):
    """
    Get character's Status record (returns None if doesn't exist).

    Args:
        character: Character object

    Returns:
        CharacterStatus or None
    """
    try:
        return CharacterStatus.objects.get(character=character)
    except CharacterStatus.DoesNotExist:
        return None


def get_total_status(character):
    """
    Get character's total Status rating.

    Args:
        character: Character object

    Returns:
        int: Total Status (0-5)
    """
    char_status = get_character_status(character)
    if not char_status:
        return 0

    return char_status.total_status


def get_status_bonus(character, context="social"):
    """
    Get dice bonus from Status for rolls.

    Status provides +1 die per 2 Status dots for relevant social rolls.

    Args:
        character: Character object
        context (str): Context of roll ("social", "intimidate", "command", etc.)

    Returns:
        int: Bonus dice
    """
    char_status = get_character_status(character)
    if not char_status:
        return 0

    # Base bonus: +1 die per 2 Status
    base_bonus = char_status.total_status // 2

    # Context-specific modifiers
    if context in ["command", "leadership"] and char_status.position:
        # Leaders get additional bonus when commanding
        if char_status.position.hierarchy_level >= 5:  # Prince-level
            base_bonus += 2
        elif char_status.position.hierarchy_level >= 3:  # Primogen-level
            base_bonus += 1

    return base_bonus


def set_earned_status(character, value, reason="", changed_by=None):
    """
    Set character's earned Status.

    Args:
        character: Character object
        value (int): New earned Status value (0-5)
        reason (str): Reason for change
        changed_by: Character/account who made the change

    Returns:
        CharacterStatus: Updated status record
    """
    char_status = get_or_create_character_status(character)

    old_value = char_status.earned_status
    char_status.earned_status = max(0, min(5, value))

    # Log history
    change = char_status.earned_status - old_value
    if change != 0:
        char_status.add_status_history(
            change,
            reason or f"Status adjusted to {char_status.earned_status}",
            str(changed_by) if changed_by else "System"
        )

    char_status.save()
    return char_status


def modify_earned_status(character, change, reason="", changed_by=None):
    """
    Modify character's earned Status by a delta.

    Args:
        character: Character object
        change (int): Change amount (+/-)
        reason (str): Reason for change
        changed_by: Character/account who made the change

    Returns:
        CharacterStatus: Updated status record
    """
    char_status = get_or_create_character_status(character)

    new_value = max(0, min(5, char_status.earned_status + change))
    return set_earned_status(character, new_value, reason, changed_by)


def assign_position(character, position_name, assigned_by=None):
    """
    Assign a Camarilla position to a character.

    Args:
        character: Character object
        position_name (str): Name of position
        assigned_by: Character/account assigning position

    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        position = CamarillaPosition.objects.get(name__iexact=position_name, is_active=True)
    except CamarillaPosition.DoesNotExist:
        return (False, f"Position '{position_name}' not found or is inactive.")

    char_status = get_or_create_character_status(character)

    # Check requirements
    if position.requires_status > char_status.earned_status:
        return (False, f"Character requires {position.requires_status} earned Status to hold this position.")

    if position.requires_clan:
        char_clan = character.db.vampire.get('clan', '') if hasattr(character.db, 'vampire') else ''
        if char_clan.lower() != position.requires_clan.lower():
            return (False, f"Position requires clan {position.requires_clan}.")

    # If position is unique, remove current holder
    if position.is_unique:
        old_holders = CharacterStatus.objects.filter(position=position)
        for old_holder in old_holders:
            old_holder.position = None
            old_holder.position_status = 0
            old_holder.add_status_history(
                -position.status_granted,
                f"Removed from position: {position.name}",
                str(assigned_by) if assigned_by else "System"
            )
            old_holder.save()

    # Assign position
    char_status.position = position
    char_status.position_status = position.status_granted
    char_status.sect = position.sect
    char_status.add_status_history(
        position.status_granted,
        f"Appointed to position: {position.name}",
        str(assigned_by) if assigned_by else "System"
    )
    char_status.save()

    return (True, f"{character.key} appointed as {position.name}.")


def remove_position(character, removed_by=None):
    """
    Remove character's position.

    Args:
        character: Character object
        removed_by: Character/account removing position

    Returns:
        tuple: (success: bool, message: str)
    """
    char_status = get_character_status(character)

    if not char_status or not char_status.position:
        return (False, f"{character.key} does not hold a position.")

    position_name = char_status.position.name
    status_lost = char_status.position_status

    char_status.position = None
    char_status.position_status = 0
    char_status.add_status_history(
        -status_lost,
        f"Removed from position: {position_name}",
        str(removed_by) if removed_by else "System"
    )
    char_status.save()

    return (True, f"{character.key} removed from position: {position_name}.")


def get_all_positions():
    """
    Get all active Camarilla positions.

    Returns:
        QuerySet: Active positions ordered by hierarchy
    """
    return CamarillaPosition.objects.filter(is_active=True).order_by('-hierarchy_level', 'name')


def get_position_holders(position_name):
    """
    Get all characters holding a specific position.

    Args:
        position_name (str): Position name

    Returns:
        QuerySet: Characters holding this position
    """
    try:
        position = CamarillaPosition.objects.get(name__iexact=position_name, is_active=True)
        return CharacterStatus.objects.filter(position=position)
    except CamarillaPosition.DoesNotExist:
        return CharacterStatus.objects.none()


def create_status_request(character, request_type, reason, **kwargs):
    """
    Create a status change request.

    Args:
        character: Character making request
        request_type (str): Type of request
        reason (str): IC justification
        **kwargs: Additional fields (requested_change, requested_position, ooc_notes)

    Returns:
        StatusRequest: Created request
    """
    request = StatusRequest.objects.create(
        character=character,
        request_type=request_type,
        reason=reason,
        requested_change=kwargs.get('requested_change', 0),
        requested_position=kwargs.get('requested_position', None),
        ooc_notes=kwargs.get('ooc_notes', ''),
        status='pending'
    )

    return request


def get_pending_status_requests():
    """
    Get all pending status requests.

    Returns:
        QuerySet: Pending requests
    """
    return StatusRequest.objects.filter(status='pending').order_by('-created_date')


def get_character_status_requests(character, status=None):
    """
    Get status requests for a character.

    Args:
        character: Character object
        status (str, optional): Filter by status (pending, approved, denied)

    Returns:
        QuerySet: Character's requests
    """
    requests = StatusRequest.objects.filter(character=character)

    if status:
        requests = requests.filter(status=status)

    return requests.order_by('-created_date')


def format_status_display(character):
    """
    Format character's Status for display with colors and symbols.

    Args:
        character: Character object

    Returns:
        str: Formatted status display
    """
    char_status = get_character_status(character)

    if not char_status:
        return f"|wNo Status record|n"

    # Simple header
    output = []
    output.append(f"|w=== Status Summary for {character.key} ===|n\n")

    # Total Status
    total = char_status.total_status
    dots = "•" * total
    empty_dots = "○" * (5 - total)

    output.append(f"|wTotal Status:|n {dots}{empty_dots} ({total}/5)")

    # Breakdown
    breakdown = []
    if char_status.earned_status > 0:
        breakdown.append(f"Earned: {char_status.earned_status}")
    if char_status.position_status > 0:
        breakdown.append(f"Position: {char_status.position_status}")
    if char_status.temporary_status != 0:
        breakdown.append(f"Temporary: {char_status.temporary_status:+d}")

    if breakdown:
        output.append(f"  ({', '.join(breakdown)})")

    # Position
    if char_status.position:
        output.append(f"\n|wPosition:|n {char_status.position.name}")
        if char_status.position.title:
            output.append(f"  \"{char_status.position.title}\"")
        output.append(f"  Status Granted: {char_status.position.status_granted}")

    # Sect
    output.append(f"\n|wSect:|n {char_status.sect}")

    # Mechanical bonus
    bonus = char_status.get_status_bonus()
    if bonus > 0:
        output.append(f"\n|wSocial Roll Bonus:|n +{bonus} dice")

    # Reputation (if set)
    if char_status.reputation:
        output.append(f"\n|wReputation:|n")
        output.append(f"{char_status.reputation}")

    return "\n".join(output)


def initialize_default_positions():
    """
    Initialize default Camarilla positions.

    This should be run once during setup to create standard positions.
    """
    default_positions = [
        {
            "name": "Prince",
            "title": "Prince of Athens",
            "status_granted": 3,
            "hierarchy_level": 10,
            "description": "Ruler of the city domain, arbiter of the Traditions",
            "is_unique": True,
            "requires_status": 2,
            "sect": "Camarilla"
        },
        {
            "name": "Primogen",
            "title": "Primogen Council Member",
            "status_granted": 2,
            "hierarchy_level": 8,
            "description": "Clan representative on the Primogen Council",
            "is_unique": False,
            "requires_status": 1,
            "sect": "Camarilla"
        },
        {
            "name": "Sheriff",
            "title": "Sheriff of Athens",
            "status_granted": 2,
            "hierarchy_level": 7,
            "description": "Enforcer of the Prince's will and Traditions",
            "is_unique": True,
            "requires_status": 1,
            "sect": "Camarilla"
        },
        {
            "name": "Scourge",
            "title": "Scourge of Athens",
            "status_granted": 1,
            "hierarchy_level": 6,
            "description": "Hunter of unauthorized vampires and Thin-Bloods",
            "is_unique": True,
            "requires_status": 0,
            "sect": "Camarilla"
        },
        {
            "name": "Keeper of Elysium",
            "title": "Keeper of Elysium",
            "status_granted": 2,
            "hierarchy_level": 7,
            "description": "Guardian of Elysium and enforcer of its neutrality",
            "is_unique": True,
            "requires_status": 1,
            "sect": "Camarilla"
        },
        {
            "name": "Whip",
            "title": "Clan Whip",
            "status_granted": 1,
            "hierarchy_level": 5,
            "description": "Assistant to a Primogen, enforcer of clan discipline",
            "is_unique": False,
            "requires_status": 0,
            "sect": "Camarilla"
        },
        {
            "name": "Harpy",
            "title": "Harpy",
            "status_granted": 1,
            "hierarchy_level": 6,
            "description": "Arbiter of social standing and boons",
            "is_unique": False,
            "requires_status": 1,
            "sect": "Camarilla"
        },
        {
            "name": "Seneschal",
            "title": "Seneschal of Athens",
            "status_granted": 2,
            "hierarchy_level": 9,
            "description": "Second to the Prince, acts in their absence",
            "is_unique": True,
            "requires_status": 2,
            "sect": "Camarilla"
        },
    ]

    created_count = 0
    for pos_data in default_positions:
        position, created = CamarillaPosition.objects.get_or_create(
            name=pos_data["name"],
            defaults=pos_data
        )
        if created:
            created_count += 1

    return created_count


# =============================================================================
# FORMATTING FUNCTIONS (Presentation Layer)
# =============================================================================

def format_character_status(character, char_status):
    """
    Format character status for display.

    Args:
        character: Character object
        char_status: CharacterStatus object

    Returns:
        str: Formatted character status display
    """
    output = []
    output.append("\n|c*" + "=" * 78 + "*|n")
    output.append(f"|c|||n |wSTATUS: {character.key.upper()}|n{' ' * (62 - len(character.key))} |c|||n")
    output.append("|c*" + "=" * 78 + "*|n\n")

    # Total Status
    total = char_status.total_status
    dots = "•" * total
    empty_dots = "○" * (5 - total)
    output.append(f"|wTotal Status:|n {dots}{empty_dots} ({total}/5)")

    # Breakdown
    breakdown = []
    if char_status.earned_status > 0:
        breakdown.append(f"Earned: {char_status.earned_status}")
    if char_status.position_status > 0:
        breakdown.append(f"Position: {char_status.position_status}")
    if char_status.temporary_status != 0:
        breakdown.append(f"Temporary: {char_status.temporary_status:+d}")

    if breakdown:
        output.append(f"  ({', '.join(breakdown)})")

    # Position
    if char_status.position:
        output.append(f"\n|wPosition:|n {char_status.position.name}")
        if char_status.position.title:
            output.append(f"  \"{char_status.position.title}\"")
        output.append(f"  {char_status.position.description}")

    # Sect
    output.append(f"\n|wSect:|n {char_status.sect}")

    # Mechanical Bonus
    bonus = char_status.get_status_bonus()
    if bonus > 0:
        output.append(f"\n|wSocial Roll Bonus:|n +{bonus} dice")

    # Reputation
    if char_status.reputation:
        output.append(f"\n|wReputation:|n")
        output.append(f"{char_status.reputation}")

    return "\n".join(output)


def format_status_history(char_status):
    """
    Format status history for display.

    Args:
        char_status: CharacterStatus object

    Returns:
        str: Formatted status history display
    """
    output = []
    output.append("\n|c*" + "=" * 78 + "*|n")
    output.append(f"|c|||n |wSTATUS HISTORY|n{' ' * 60} |c|||n")
    output.append("|c*" + "=" * 78 + "*|n\n")

    for entry in reversed(char_status.status_history[-10:]):  # Last 10 entries
        date = entry.get('date', 'Unknown')[:10]  # Just the date part
        change = entry.get('change', 0)
        reason = entry.get('reason', 'No reason given')
        changed_by = entry.get('changed_by', 'Unknown')
        new_total = entry.get('new_total', 0)

        change_str = f"|g+{change}|n" if change > 0 else f"|r{change}|n" if change < 0 else "±0"

        output.append(f"{date} - {change_str} → {new_total}")
        output.append(f"  {reason}")
        output.append(f"  (by {changed_by})")
        output.append("")

    return "\n".join(output)


def format_positions_list(positions):
    """
    Format positions list for display.

    Args:
        positions: QuerySet of CamarillaPosition objects

    Returns:
        str: Formatted positions list display
    """
    output = []
    output.append("\n|c*" + "=" * 78 + "*|n")

    # Header
    header_content = "|w{:<20} {:<8} {:<44}|n".format("Position", "Bonus", "Description")
    output.append(f"|c|||n {header_content} |c|||n")
    output.append("|c*" + "=" * 78 + "*|n")

    first_pos = True
    for position in positions:
        holders = get_position_holders(position.name)
        holder_count = holders.count()

        # Add divider between positions
        if not first_pos:
            output.append("|c|||n" + "-" * 78 + "|c|||n")
        first_pos = False

        bonus_str = f"+{position.status_granted}" if position.status_granted > 0 else str(position.status_granted)
        description = position.description[:44] + "..." if len(position.description) > 44 else position.description

        row_content = "|w{:<20} {:<8} {:<44}|n".format(position.name, bonus_str, description)
        output.append(f"|c|||n {row_content} |c|||n")

        # Holder info (if any)
        if holder_count > 0:
            holder_names = ", ".join([h.character.key for h in holders])
            holder_line = f"  |wHolder(s):|n {holder_names}"
            # Pad to 74 chars
            holder_line = f"{holder_line:<74}"
            output.append(f"|c|||n {holder_line} |c|||n")
        elif position.is_unique:
            vacant_line = f"  (Vacant)"
            vacant_line = f"{vacant_line:<74}"
            output.append(f"|c|||n {vacant_line} |c|||n")

    output.append("|c*" + "=" * 78 + "*|n")
    return "\n".join(output)


def format_position_detail(position):
    """
    Format position detail for display.

    Args:
        position: CamarillaPosition object

    Returns:
        str: Formatted position detail display
    """
    holders = get_position_holders(position.name)

    output = []
    output.append("\n|c*" + "=" * 78 + "*|n")
    output.append(f"|c|||n |w{position.name.upper()}|n{' ' * (72 - len(position.name))} |c|||n")
    output.append("|c*" + "=" * 78 + "*|n\n")

    # Status granted
    dots = "•" * position.status_granted
    empty_dots = "○" * (5 - position.status_granted)
    output.append(f"|wStatus Granted:|n {dots}{empty_dots} ({position.status_granted})")

    # Hierarchy level
    output.append(f"|wHierarchy Level:|n {position.hierarchy_level}")

    # Description
    output.append(f"\n|wDescription:|n")
    output.append(f"{position.description}")

    # Requirements
    if position.requires_status > 0:
        output.append(f"\n|wRequirements:|n {position.requires_status} Status")

    # Unique/Multiple
    if position.is_unique:
        output.append(f"\n|wType:|n Unique position (only one holder)")
    else:
        output.append(f"\n|wType:|n Multiple holders allowed")

    # Current holders
    if holders.exists():
        output.append(f"\n|wCurrent Holder(s):|n")
        for holder in holders:
            output.append(f"  {holder.character.key}")
    else:
        output.append(f"\n(Currently vacant)")

    return "\n".join(output)
