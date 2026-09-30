"""
Boons System Utility Functions

Helper functions for managing boons (Prestation) in Kindred society.
"""

from .models import Boon, BoonLedger


def get_or_create_ledger(character):
    """
    Get or create a boon ledger for a character.

    Args:
        character: Character object

    Returns:
        BoonLedger: Character's boon ledger
    """
    ledger, created = BoonLedger.objects.get_or_create(
        character=character,
        defaults={
            'trivial_owed': 0,
            'minor_owed': 0,
            'major_owed': 0,
            'blood_owed': 0,
            'life_owed': 0,
            'trivial_held': 0,
            'minor_held': 0,
            'major_held': 0,
            'blood_held': 0,
            'life_held': 0,
            'total_debt_weight': 0,
            'total_credit_weight': 0,
            'net_weight': 0
        }
    )

    if created:
        ledger.recalculate()

    return ledger


def update_ledger(character):
    """
    Update a character's boon ledger.

    Args:
        character: Character object

    Returns:
        BoonLedger: Updated ledger
    """
    ledger = get_or_create_ledger(character)
    ledger.recalculate()
    return ledger


def offer_boon(debtor, creditor, boon_type, description, witnesses=None, is_public=True):
    """
    Create a new boon offer.

    Args:
        debtor: Character who will owe the boon
        creditor: Character to whom the boon will be owed
        boon_type (str): Type of boon (trivial, minor, major, blood, life)
        description (str): Description of the favor
        witnesses (list, optional): List of witness characters
        is_public (bool): Whether the boon is publicly known

    Returns:
        tuple: (success: bool, boon: Boon or None, message: str)
    """
    # Validate boon type
    valid_types = ['trivial', 'minor', 'major', 'blood', 'life']
    if boon_type not in valid_types:
        return (False, None, f"Invalid boon type. Must be one of: {', '.join(valid_types)}")

    # Can't owe a boon to yourself
    if debtor == creditor:
        return (False, None, "You cannot owe a boon to yourself.")

    # Create boon
    boon = Boon.objects.create(
        debtor=debtor,
        creditor=creditor,
        boon_type=boon_type,
        description=description,
        status='offered',
        is_public=is_public
    )

    # Add witnesses
    if witnesses:
        for witness in witnesses:
            boon.witnesses.add(witness)

    boon.save()

    return (True, boon, f"Boon offered: {debtor.key} will owe {creditor.key} a {boon_type} boon.")


def accept_boon(boon_id, character=None):
    """
    Accept an offered boon.

    Args:
        boon_id (int): Boon ID
        character (optional): Character accepting (for validation)

    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        boon = Boon.objects.get(id=boon_id)
    except Boon.DoesNotExist:
        return (False, "Boon not found.")

    # Validate acceptance (debtor accepts their debt)
    if character and boon.debtor != character:
        return (False, "Only the debtor can accept this boon.")

    success, message = boon.accept()

    if success:
        # Update both ledgers
        update_ledger(boon.debtor)
        update_ledger(boon.creditor)

    return (success, message)


def decline_boon(boon_id, reason="", character=None):
    """
    Decline an offered boon.

    Args:
        boon_id (int): Boon ID
        reason (str): Reason for declining
        character (optional): Character declining (for validation)

    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        boon = Boon.objects.get(id=boon_id)
    except Boon.DoesNotExist:
        return (False, "Boon not found.")

    # Validate decline (debtor declines)
    if character and boon.debtor != character:
        return (False, "Only the debtor can decline this boon.")

    return boon.decline(reason)


def call_in_boon(boon_id, description, character=None):
    """
    Call in an accepted boon.

    Args:
        boon_id (int): Boon ID
        description (str): Description of what is being asked
        character (optional): Character calling in (for validation)

    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        boon = Boon.objects.get(id=boon_id)
    except Boon.DoesNotExist:
        return (False, "Boon not found.")

    # Validate call-in (creditor calls in)
    if character and boon.creditor != character:
        return (False, "Only the creditor can call in this boon.")

    return boon.call_in(description)


def fulfill_boon(boon_id, description, character=None):
    """
    Mark a boon as fulfilled.

    Args:
        boon_id (int): Boon ID
        description (str): Description of how it was fulfilled
        character (optional): Character fulfilling (for validation)

    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        boon = Boon.objects.get(id=boon_id)
    except Boon.DoesNotExist:
        return (False, "Boon not found.")

    # Validate fulfillment (debtor fulfills, or creditor acknowledges)
    if character and character not in [boon.debtor, boon.creditor]:
        return (False, "Only the debtor or creditor can mark this boon as fulfilled.")

    success, message = boon.fulfill(description)

    if success:
        # Update both ledgers
        update_ledger(boon.debtor)
        update_ledger(boon.creditor)

    return (success, message)


def cancel_boon(boon_id, reason="", character=None):
    """
    Cancel a boon (mutual agreement or staff).

    Args:
        boon_id (int): Boon ID
        reason (str): Reason for cancellation
        character (optional): Character canceling (for validation)

    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        boon = Boon.objects.get(id=boon_id)
    except Boon.DoesNotExist:
        return (False, "Boon not found.")

    success, message = boon.cancel(reason)

    if success:
        # Update both ledgers
        update_ledger(boon.debtor)
        update_ledger(boon.creditor)

    return (success, message)


def dispute_boon(boon_id, reason, character=None):
    """
    Dispute a boon (requires Harpy intervention).

    Args:
        boon_id (int): Boon ID
        reason (str): Reason for dispute
        character (optional): Character disputing

    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        boon = Boon.objects.get(id=boon_id)
    except Boon.DoesNotExist:
        return (False, "Boon not found.")

    return boon.dispute(reason)


def acknowledge_boon(boon_id, harpy_character):
    """
    Officially acknowledge a boon (Harpy function).

    Args:
        boon_id (int): Boon ID
        harpy_character: Harpy character object

    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        boon = Boon.objects.get(id=boon_id)
    except Boon.DoesNotExist:
        return (False, "Boon not found.")

    return boon.acknowledge_by_harpy(harpy_character)


def get_boons_owed_by(character, status='accepted'):
    """
    Get all boons owed by a character.

    Args:
        character: Character object
        status (str, optional): Filter by status

    Returns:
        QuerySet: Boons owed by this character
    """
    boons = Boon.objects.filter(debtor=character)

    if status:
        boons = boons.filter(status=status)

    return boons.order_by('-created_date')


def get_boons_held_by(character, status='accepted'):
    """
    Get all boons held by a character (owed to them).

    Args:
        character: Character object
        status (str, optional): Filter by status

    Returns:
        QuerySet: Boons held by this character
    """
    boons = Boon.objects.filter(creditor=character)

    if status:
        boons = boons.filter(status=status)

    return boons.order_by('-created_date')


def get_boons_between(char1, char2):
    """
    Get all boons between two characters.

    Args:
        char1: First character
        char2: Second character

    Returns:
        QuerySet: All boons between these characters
    """
    from django.db.models import Q

    return Boon.objects.filter(
        (Q(debtor=char1) & Q(creditor=char2)) |
        (Q(debtor=char2) & Q(creditor=char1))
    ).order_by('-created_date')


def get_pending_boons_for(character):
    """
    Get boons pending action from a character.

    Args:
        character: Character object

    Returns:
        dict: Pending boons categorized
            - to_accept: Offered boons where character is debtor
            - called_in_on_you: Boons called in where character is debtor
            - awaiting_fulfillment: Boons called in where character is creditor
    """
    return {
        'to_accept': Boon.objects.filter(debtor=character, status='offered'),
        'called_in_on_you': Boon.objects.filter(debtor=character, status='called_in'),
        'awaiting_fulfillment': Boon.objects.filter(creditor=character, status='called_in')
    }


def get_all_public_boons():
    """
    Get all public boons (for Harpy review).

    Returns:
        QuerySet: Public boons
    """
    return Boon.objects.filter(is_public=True).order_by('-created_date')


def get_net_boon_position(char1, char2):
    """
    Get net boon position between two characters.

    Args:
        char1: First character
        char2: Second character

    Returns:
        dict: Net boon position
            - char1_owes_char2: Weight of boons char1 owes char2
            - char2_owes_char1: Weight of boons char2 owes char1
            - net: Net position (positive = char1 holds more, negative = char1 owes more)
    """
    # Char1 owes char2
    boons_1_to_2 = Boon.objects.filter(
        debtor=char1,
        creditor=char2,
        status='accepted'
    )

    weight_1_to_2 = sum([boon.get_boon_weight() for boon in boons_1_to_2])

    # Char2 owes char1
    boons_2_to_1 = Boon.objects.filter(
        debtor=char2,
        creditor=char1,
        status='accepted'
    )

    weight_2_to_1 = sum([boon.get_boon_weight() for boon in boons_2_to_1])

    return {
        'char1_owes_char2': weight_1_to_2,
        'char2_owes_char1': weight_2_to_1,
        'net': weight_2_to_1 - weight_1_to_2  # Positive if char1 holds more
    }


def format_boon_summary(character):
    """
    Format a character's boon summary for display.

    Args:
        character: Character object

    Returns:
        str: Formatted boon summary
    """
    ledger = get_or_create_ledger(character)

    lines = []

    # Debts (what you owe)
    debts = []
    if ledger.life_owed > 0:
        debts.append(f"Life: {ledger.life_owed}")
    if ledger.blood_owed > 0:
        debts.append(f"Blood: {ledger.blood_owed}")
    if ledger.major_owed > 0:
        debts.append(f"Major: {ledger.major_owed}")
    if ledger.minor_owed > 0:
        debts.append(f"Minor: {ledger.minor_owed}")
    if ledger.trivial_owed > 0:
        debts.append(f"Trivial: {ledger.trivial_owed}")

    debt_str = ", ".join(debts) if debts else "None"
    lines.append(f"Debts: {debt_str} (Weight: {ledger.total_debt_weight})")

    # Credits (what others owe you)
    credits = []
    if ledger.life_held > 0:
        credits.append(f"Life: {ledger.life_held}")
    if ledger.blood_held > 0:
        credits.append(f"Blood: {ledger.blood_held}")
    if ledger.major_held > 0:
        credits.append(f"Major: {ledger.major_held}")
    if ledger.minor_held > 0:
        credits.append(f"Minor: {ledger.minor_held}")
    if ledger.trivial_held > 0:
        credits.append(f"Trivial: {ledger.trivial_held}")

    credit_str = ", ".join(credits) if credits else "None"
    lines.append(f"Credits: {credit_str} (Weight: {ledger.total_credit_weight})")

    # Net position
    if ledger.net_weight > 0:
        lines.append(f"Net Position: +{ledger.net_weight} (In credit)")
    elif ledger.net_weight < 0:
        lines.append(f"Net Position: {ledger.net_weight} (In debt)")
    else:
        lines.append("Net Position: Balanced")

    return "\n".join(lines)


def check_harpy_permissions(character):
    """
    Check if a character has Harpy permissions.

    Args:
        character: Character object

    Returns:
        bool: True if character is a Harpy
    """
    try:
        from status.utils import get_character_status

        char_status = get_character_status(character)
        if not char_status or not char_status.position:
            return False

        return char_status.position.name.lower() == 'harpy'
    except ImportError:
        # Status system not installed
        return False


# =============================================================================
# FORMATTING FUNCTIONS (Presentation Layer)
# =============================================================================

def format_boon_ledger(caller, ledger):
    """
    Format a character's boon ledger for display.

    Args:
        caller: Character viewing the ledger
        ledger: BoonLedger object

    Returns:
        str: Formatted boon ledger display
    """
    from world.ansi_theme import (
        GOLD, PALE_IVORY, RESET, BLOOD_RED, SHADOW_GREY
    )

    output = []
    output.append("\n|c*" + "=" * 78 + "*|n")
    output.append(f"|c|||n {PALE_IVORY}BOON LEDGER: {caller.key.upper()}{RESET}{' ' * (62 - len(caller.key))} |c|||n")
    output.append("|c*" + "=" * 78 + "*|n")

    # Debts
    output.append(f"\n{PALE_IVORY}DEBTS (What You Owe):{RESET}")
    if ledger.total_debt_weight > 0:
        if ledger.life_owed > 0:
            output.append(f"  {BLOOD_RED}Life Boons:{RESET} {ledger.life_owed}")
        if ledger.blood_owed > 0:
            output.append(f"  {BLOOD_RED}Blood Boons:{RESET} {ledger.blood_owed}")
        if ledger.major_owed > 0:
            output.append(f"  {DARK_RED}Major Boons:{RESET} {ledger.major_owed}")
        if ledger.minor_owed > 0:
            output.append(f"  {GOLD}Minor Boons:{RESET} {ledger.minor_owed}")
        if ledger.trivial_owed > 0:
            output.append(f"  {SHADOW_GREY}Trivial Boons:{RESET} {ledger.trivial_owed}")
        output.append(f"  {PALE_IVORY}Total Weight:{RESET} {ledger.total_debt_weight}")
    else:
        output.append(f"  {SHADOW_GREY}None{RESET}")

    # Credits
    output.append(f"\n{PALE_IVORY}CREDITS (What Others Owe You):{RESET}")
    if ledger.total_credit_weight > 0:
        if ledger.life_held > 0:
            output.append(f"  {BLOOD_RED}Life Boons:{RESET} {ledger.life_held}")
        if ledger.blood_held > 0:
            output.append(f"  {BLOOD_RED}Blood Boons:{RESET} {ledger.blood_held}")
        if ledger.major_held > 0:
            output.append(f"  {DARK_RED}Major Boons:{RESET} {ledger.major_held}")
        if ledger.minor_held > 0:
            output.append(f"  {GOLD}Minor Boons:{RESET} {ledger.minor_held}")
        if ledger.trivial_held > 0:
            output.append(f"  {SHADOW_GREY}Trivial Boons:{RESET} {ledger.trivial_held}")
        output.append(f"  {PALE_IVORY}Total Weight:{RESET} {ledger.total_credit_weight}")
    else:
        output.append(f"  {SHADOW_GREY}None{RESET}")

    # Net position
    net_line = f"\n{PALE_IVORY}Net Position:{RESET}"
    if ledger.net_weight > 0:
        net_line += f" {GOLD}+{ledger.net_weight}{RESET} (In credit)"
    elif ledger.net_weight < 0:
        net_line += f" {BLOOD_RED}{ledger.net_weight}{RESET} (In debt)"
    else:
        net_line += f" {SHADOW_GREY}Balanced{RESET}"
    output.append(net_line)

    output.append(f"\n{SHADOW_GREY}Use |w+boon <character>|x to see boons with specific individuals.{RESET}")

    # Close the box
    output.append("\n|c*" + "=" * 78 + "*|n")

    return "\n".join(output)


def format_boons_with_character(caller, target, boons, net_position):
    """
    Format boons between two characters for display.

    Args:
        caller: Character viewing the boons
        target: Other character
        boons: QuerySet of Boon objects
        net_position: Dict with net boon position data

    Returns:
        str: Formatted boons display
    """
    from world.ansi_theme import (
        PALE_IVORY, RESET, GOLD, BLOOD_RED, SHADOW_GREY
    )

    output = []
    output.append("\n|c*" + "=" * 78 + "*|n")
    output.append(f"|c|||n {PALE_IVORY}BOONS WITH {target.key.upper()}{RESET}{' ' * (63 - len(target.key))} |c|||n")
    output.append("|c*" + "=" * 78 + "*|n")

    # Net position
    if net_position['net'] > 0:
        output.append(f"\n{PALE_IVORY}Net Position:{RESET} {GOLD}{target.key} owes you {net_position['net']} weight in boons{RESET}")
    elif net_position['net'] < 0:
        output.append(f"\n{PALE_IVORY}Net Position:{RESET} {BLOOD_RED}You owe {target.key} {abs(net_position['net'])} weight in boons{RESET}")
    else:
        output.append(f"\n{PALE_IVORY}Net Position:{RESET} {SHADOW_GREY}Balanced{RESET}")

    if not boons:
        output.append(f"\n{SHADOW_GREY}No boons between you and {target.key}.{RESET}")
        return "\n".join(output)

    # List boons
    output.append(f"\n{PALE_IVORY}Boon History:{RESET}")
    for boon in boons[:10]:  # Last 10 boons
        if boon.debtor == caller:
            direction = f"{BLOOD_RED}You owe {target.key}{RESET}"
        else:
            direction = f"{GOLD}{target.key} owes you{RESET}"

        status_color = GOLD if boon.status == 'accepted' else SHADOW_GREY
        output.append(f"\n#{boon.id} - {direction} - {PALE_IVORY}{boon.get_boon_type_display()}{RESET}")
        output.append(f"  Status: {status_color}{boon.status.title()}{RESET}")
        output.append(f"  {SHADOW_GREY}{boon.description[:60]}{'...' if len(boon.description) > 60 else ''}{RESET}")

    # Close the box
    output.append("\n|c*" + "=" * 78 + "*|n")

    return "\n".join(output)


def format_pending_boons(caller, pending):
    """
    Format pending boons for display.

    Args:
        caller: Character viewing pending boons
        pending: Dict with pending boon QuerySets

    Returns:
        str: Formatted pending boons display
    """
    from world.ansi_theme import (
        PALE_IVORY, RESET, GOLD, BLOOD_RED, SHADOW_GREY
    )

    output = []
    output.append("\n|c*" + "=" * 78 + "*|n")
    output.append(f"|c|||n {PALE_IVORY}PENDING BOONS{RESET}{' ' * 60} |c|||n")
    output.append("|c*" + "=" * 78 + "*|n")

    has_pending = False

    # To accept
    if pending['to_accept'].exists():
        has_pending = True
        output.append(f"\n{GOLD}To Accept (offered to you):{RESET}")
        for boon in pending['to_accept']:
            output.append(f"  #{boon.id} - {boon.get_boon_type_display()} from {boon.creditor.key}")
            output.append(f"    {SHADOW_GREY}{boon.description[:60]}{RESET}")
            output.append(f"    {SHADOW_GREY}Use: +boonaccept {boon.id} or +boondecline {boon.id}{RESET}")

    # Called in on you
    if pending['called_in_on_you'].exists():
        has_pending = True
        output.append(f"\n{BLOOD_RED}Called In (you must fulfill):{RESET}")
        for boon in pending['called_in_on_you']:
            output.append(f"  #{boon.id} - {boon.get_boon_type_display()} to {boon.creditor.key}")
            output.append(f"    {SHADOW_GREY}Request: {boon.called_in_description[:55]}{RESET}")
            output.append(f"    {SHADOW_GREY}Use: +boonfulfill {boon.id} = <description>{RESET}")

    # Awaiting fulfillment
    if pending['awaiting_fulfillment'].exists():
        has_pending = True
        output.append(f"\n{PALE_IVORY}Awaiting Fulfillment (you called in):{RESET}")
        for boon in pending['awaiting_fulfillment']:
            output.append(f"  #{boon.id} - {boon.get_boon_type_display()} from {boon.debtor.key}")
            output.append(f"    {SHADOW_GREY}Request: {boon.called_in_description[:55]}{RESET}")

    if not has_pending:
        output.append(f"\n{SHADOW_GREY}No boons pending action.{RESET}")

    # Close the box
    output.append("\n|c*" + "=" * 78 + "*|n")

    return "\n".join(output)
