"""
Social Utility Functions for V5 System

Coterie management and social structure utilities.
"""

from datetime import datetime
from evennia.utils import search


def create_coterie(creator, name, description):
    """
    Create a new coterie with the creator as leader.

    Args:
        creator: Character object who is creating the coterie
        name (str): Name of the coterie
        description (str): Description of the coterie

    Returns:
        tuple: (success: bool, message: str)
    """
    # Check if creator already has a coterie
    if hasattr(creator.db, 'coterie') and creator.db.coterie:
        return (False, "You are already in a coterie. Leave it first before creating a new one.")

    # Validate name
    if not name or len(name) < 3:
        return (False, "Coterie name must be at least 3 characters long.")

    if not description or len(description) < 10:
        return (False, "Coterie description must be at least 10 characters long.")

    # Create coterie structure
    coterie = {
        'name': name,
        'description': description,
        'leader': creator.dbref,
        'members': [],
        'resources': {
            'domain': 0,
            'haven': 0,
            'herd': 0,
            'contacts': 0
        },
        'created': datetime.now().isoformat(),
        'disbanded': None
    }

    # Store on character
    creator.db.coterie = coterie

    # Initialize invitations list if not exists
    if not hasattr(creator.db, 'coterie_invitations'):
        creator.db.coterie_invitations = []

    return (True, f"Coterie '{name}' created successfully. You are the leader.")


def add_coterie_member(coterie_owner, character, rank='member'):
    """
    Add a member to a coterie.

    Args:
        coterie_owner: Character who owns the coterie (leader)
        character: Character to add
        rank (str): Rank to assign ('lieutenant' or 'member')

    Returns:
        tuple: (success: bool, message: str)
    """
    # Validate coterie exists
    if not hasattr(coterie_owner.db, 'coterie') or not coterie_owner.db.coterie:
        return (False, "You don't have a coterie.")

    # Validate rank
    if rank not in ['lieutenant', 'member']:
        return (False, "Rank must be 'lieutenant' or 'member'.")

    # Check if character already in a coterie
    if hasattr(character.db, 'coterie') and character.db.coterie:
        return (False, f"{character.key} is already in a coterie.")

    # Check if already a member
    coterie = coterie_owner.db.coterie
    for member in coterie['members']:
        if member['character'] == character.dbref:
            return (False, f"{character.key} is already a member of this coterie.")

    # Add member
    coterie['members'].append({
        'character': character.dbref,
        'rank': rank
    })
    coterie_owner.db.coterie = coterie

    # Set coterie reference on member
    character.db.coterie = {
        'leader': coterie['leader'],
        'name': coterie['name']
    }

    return (True, f"{character.key} added to coterie as {rank}.")


def remove_coterie_member(coterie_owner, character):
    """
    Remove a member from a coterie.

    Args:
        coterie_owner: Character who owns the coterie (leader)
        character: Character to remove

    Returns:
        tuple: (success: bool, message: str)
    """
    # Validate coterie exists
    if not hasattr(coterie_owner.db, 'coterie') or not coterie_owner.db.coterie:
        return (False, "You don't have a coterie.")

    coterie = coterie_owner.db.coterie

    # Find and remove member
    for i, member in enumerate(coterie['members']):
        if member['character'] == character.dbref:
            coterie['members'].pop(i)
            coterie_owner.db.coterie = coterie

            # Remove coterie reference from character
            if hasattr(character.db, 'coterie'):
                character.db.coterie = None

            return (True, f"{character.key} removed from coterie.")

    return (False, f"{character.key} is not a member of this coterie.")


def leave_coterie(character):
    """
    Leave current coterie.

    Args:
        character: Character leaving the coterie

    Returns:
        tuple: (success: bool, message: str)
    """
    if not hasattr(character.db, 'coterie') or not character.db.coterie:
        return (False, "You are not in a coterie.")

    coterie_data = character.db.coterie

    # If leader, can't leave (must disband)
    if coterie_data.get('leader') == character.dbref:
        return (False, "As the leader, you must disband the coterie instead of leaving.")

    # Find leader character
    leader_dbref = coterie_data.get('leader')
    leader = search.search_object(leader_dbref)
    if not leader:
        # Leader not found, just clear coterie data
        character.db.coterie = None
        return (True, "You have left the coterie.")

    leader = leader[0]

    # Remove from leader's coterie
    if hasattr(leader.db, 'coterie') and leader.db.coterie:
        coterie = leader.db.coterie
        coterie['members'] = [m for m in coterie['members'] if m['character'] != character.dbref]
        leader.db.coterie = coterie

    # Clear own coterie reference
    character.db.coterie = None

    return (True, f"You have left the coterie '{coterie_data.get('name', 'Unknown')}'.")


def get_coterie_info(character):
    """
    Get coterie information for a character.

    Args:
        character: Character object

    Returns:
        dict or None: Coterie data or None if not in coterie
    """
    if not hasattr(character.db, 'coterie') or not character.db.coterie:
        return None

    coterie_data = character.db.coterie

    # If member, get full info from leader
    if 'leader' in coterie_data and coterie_data['leader'] != character.dbref:
        leader_dbref = coterie_data['leader']
        leader = search.search_object(leader_dbref)
        if leader and hasattr(leader[0].db, 'coterie'):
            return leader[0].db.coterie

    return coterie_data


def get_character_role(character):
    """
    Get character's role in their coterie.

    Args:
        character: Character object

    Returns:
        str: 'leader', 'lieutenant', 'member', or None
    """
    coterie = get_coterie_info(character)
    if not coterie:
        return None

    if coterie['leader'] == character.dbref:
        return 'leader'

    for member in coterie.get('members', []):
        if member['character'] == character.dbref:
            return member['rank']

    return None


def set_coterie_resources(coterie_owner, resource_type, value):
    """
    Set coterie resource value.

    Args:
        coterie_owner: Character who owns the coterie (leader)
        resource_type (str): Type of resource (domain, haven, herd, contacts)
        value (int): Value to set (0-5)

    Returns:
        tuple: (success: bool, message: str)
    """
    # Validate coterie exists
    if not hasattr(coterie_owner.db, 'coterie') or not coterie_owner.db.coterie:
        return (False, "You don't have a coterie.")

    # Validate resource type
    valid_resources = ['domain', 'haven', 'herd', 'contacts']
    if resource_type not in valid_resources:
        return (False, f"Invalid resource type. Must be one of: {', '.join(valid_resources)}")

    # Validate value
    try:
        value = int(value)
        if value < 0 or value > 5:
            return (False, "Resource value must be between 0 and 5.")
    except ValueError:
        return (False, "Resource value must be a number.")

    # Set resource
    coterie = coterie_owner.db.coterie
    coterie['resources'][resource_type] = value
    coterie_owner.db.coterie = coterie

    return (True, f"Coterie {resource_type} set to {value}.")


def get_coterie_resources(coterie_owner):
    """
    Get coterie resources.

    Args:
        coterie_owner: Character who owns the coterie

    Returns:
        dict: Resources dictionary or empty dict
    """
    if not hasattr(coterie_owner.db, 'coterie') or not coterie_owner.db.coterie:
        return {}

    return coterie_owner.db.coterie.get('resources', {})


def is_coterie_leader(character):
    """
    Check if character is a coterie leader.

    Args:
        character: Character object

    Returns:
        bool: True if leader, False otherwise
    """
    if not hasattr(character.db, 'coterie') or not character.db.coterie:
        return False

    coterie = character.db.coterie
    return coterie.get('leader') == character.dbref


def get_coterie_members(coterie_owner):
    """
    Get list of coterie members with their ranks.

    Args:
        coterie_owner: Character who owns the coterie

    Returns:
        list: List of member dictionaries
    """
    if not hasattr(coterie_owner.db, 'coterie') or not coterie_owner.db.coterie:
        return []

    coterie = coterie_owner.db.coterie
    members_data = []

    # Add leader
    leader_char = search.search_object(coterie['leader'])
    if leader_char:
        members_data.append({
            'character': leader_char[0],
            'rank': 'leader'
        })

    # Add other members
    for member in coterie.get('members', []):
        member_char = search.search_object(member['character'])
        if member_char:
            members_data.append({
                'character': member_char[0],
                'rank': member['rank']
            })

    return members_data


def invite_to_coterie(leader, target):
    """
    Invite a character to join the coterie.

    Args:
        leader: Character doing the inviting (must be leader)
        target: Character being invited

    Returns:
        tuple: (success: bool, message: str)
    """
    # Validate leader has coterie
    if not is_coterie_leader(leader):
        return (False, "You are not a coterie leader.")

    # Check if target already in a coterie
    if hasattr(target.db, 'coterie') and target.db.coterie:
        return (False, f"{target.key} is already in a coterie.")

    # Initialize invitations list
    if not hasattr(target.db, 'coterie_invitations'):
        target.db.coterie_invitations = []

    # Check if already invited
    for inv in target.db.coterie_invitations:
        if inv['leader'] == leader.dbref:
            return (False, f"{target.key} already has a pending invitation from you.")

    # Add invitation
    coterie = leader.db.coterie
    target.db.coterie_invitations.append({
        'leader': leader.dbref,
        'coterie_name': coterie['name'],
        'invited_at': datetime.now().isoformat()
    })

    return (True, f"Invitation sent to {target.key}.")


def accept_invitation(character, leader_name):
    """
    Accept a coterie invitation.

    Args:
        character: Character accepting
        leader_name (str): Name of the leader who invited

    Returns:
        tuple: (success: bool, message: str)
    """
    # Check invitations
    if not hasattr(character.db, 'coterie_invitations'):
        return (False, "You have no pending coterie invitations.")

    # Find leader
    leader = search.search_object(leader_name, typeclass='typeclasses.characters.Character')
    if not leader:
        return (False, f"Could not find character '{leader_name}'.")

    leader = leader[0]

    # Find invitation
    invitation = None
    for inv in character.db.coterie_invitations:
        if inv['leader'] == leader.dbref:
            invitation = inv
            break

    if not invitation:
        return (False, f"You have no pending invitation from {leader.key}.")

    # Add to coterie
    success, message = add_coterie_member(leader, character, 'member')

    if success:
        # Remove invitation
        character.db.coterie_invitations = [
            inv for inv in character.db.coterie_invitations
            if inv['leader'] != leader.dbref
        ]

    return (success, message)


def disband_coterie(leader):
    """
    Disband a coterie (leader only).

    Args:
        leader: Character disbanding the coterie

    Returns:
        tuple: (success: bool, message: str)
    """
    if not is_coterie_leader(leader):
        return (False, "Only the coterie leader can disband the coterie.")

    coterie = leader.db.coterie
    coterie_name = coterie['name']

    # Remove coterie from all members
    for member in coterie.get('members', []):
        member_char = search.search_object(member['character'])
        if member_char and hasattr(member_char[0].db, 'coterie'):
            member_char[0].db.coterie = None

    # Mark as disbanded and clear from leader
    coterie['disbanded'] = datetime.now().isoformat()
    leader.db.coterie = None

    return (True, f"Coterie '{coterie_name}' has been disbanded.")


def set_member_rank(leader, target, new_rank):
    """
    Change a member's rank (promote/demote).

    Args:
        leader: Coterie leader
        target: Character whose rank to change
        new_rank (str): New rank ('lieutenant' or 'member')

    Returns:
        tuple: (success: bool, message: str)
    """
    if not is_coterie_leader(leader):
        return (False, "Only the coterie leader can change ranks.")

    if new_rank not in ['lieutenant', 'member']:
        return (False, "Rank must be 'lieutenant' or 'member'.")

    if target == leader:
        return (False, "You cannot change your own rank.")

    coterie = leader.db.coterie

    # Find member and update rank
    for member in coterie.get('members', []):
        if member['character'] == target.dbref:
            old_rank = member['rank']
            member['rank'] = new_rank
            leader.db.coterie = coterie

            action = "promoted to" if new_rank == 'lieutenant' else "demoted to"
            return (True, f"{target.key} {action} {new_rank}.")

    return (False, f"{target.key} is not a member of your coterie.")
