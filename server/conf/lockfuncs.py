"""
Custom lock functions for beckonmu.

Lock functions are callables that receive an accessing object,
an accessed object, and a string denoting what kind of access is
attempted.

Lock functions should return True if access is granted, False otherwise.

Example:
    def mylock(accessing_obj, accessed_obj, *args, **kwargs):
        '''
        A simple example lock function.
        '''
        return accessing_obj.id == 1

Usage in locks:
    "examine:mylock()"

"""

# Add your custom lock functions below.
# They will be available for use in lock definitions throughout the game.


def _account_of(accessing_obj):
    """The Account behind `accessing_obj` (an Account, or a puppeted Object), or None."""
    from evennia.utils.utils import inherits_from

    if inherits_from(accessing_obj, "evennia.objects.objects.DefaultObject"):
        accessing_obj = accessing_obj.account
    if accessing_obj is None or not inherits_from(accessing_obj, "evennia.accounts.accounts.DefaultAccount"):
        return None
    return accessing_obj


def char_owner(accessing_obj, accessed_obj, *args, **kwargs):
    """
    Pass if the accessing account owns the accessed character.

    Usage:
        char_owner()

    Ownership is `traits.CharacterBio.account` (set when the website creates
    the character). It is never the character's current puppeteer.
    """
    account = _account_of(accessing_obj)
    if account is None or not getattr(accessed_obj, "id", None):
        return False
    from traits.models import CharacterBio

    return CharacterBio.objects.filter(character_id=accessed_obj.id, account_id=account.id).exists()


def char_approved(accessing_obj, accessed_obj, *args, **kwargs):
    """
    Pass if the accessed character's application is approved.

    Usage:
        char_approved()

    Approval is `traits.CharacterBio.status == "approved"`; it is stored
    nowhere else.
    """
    if not getattr(accessed_obj, "id", None):
        return False
    from traits.models import CharacterBio

    return CharacterBio.objects.filter(character_id=accessed_obj.id, status="approved").exists()
