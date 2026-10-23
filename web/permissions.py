"""
One authority model for web views: Evennia permission strings.

Web code checks the same permission hierarchy as in-game commands
(`perm(Builder)`, `perm(Admin)`, ...) instead of Django's `is_staff` flag, so a
Builder promoted in game has the same rights on the website, and an `is_staff`
flag alone grants nothing.
"""


def has_perm(user, perm):
    """
    Return True if `user` holds Evennia permission `perm` or a higher one.

    Superusers pass every check (unless quelled), as in game. Anonymous or
    unauthenticated users never pass.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    check = getattr(user, "check_permstring", None)
    if check is None:
        return False
    return bool(check(perm))
