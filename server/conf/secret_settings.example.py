"""
Example per-host settings for TheBeckoningMU.

The real file is server/conf/secret_settings.py. It is gitignored and must
never be committed. Create it with:

    evennia --initmissing

which writes a fresh random SECRET_KEY. Then copy in whichever of the
settings below this host needs. Anything set here overrides
server/conf/settings.py. The server refuses to start if the file is missing
or if SECRET_KEY is still Evennia's public default.
"""

# Signs Django sessions, cookies and password-reset tokens. Keep it unique per
# deployment and keep it private. `evennia --initmissing` generates one; to
# make one by hand:
#
#     python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
#
# Changing it logs everyone out of the website. Left commented out here so a
# straight copy of this file is refused at startup rather than shipping a
# known key.
# SECRET_KEY = "<the value written by evennia --initmissing>"

# Hostnames the website may be served under. Evennia's default is ["*"]; for a
# public deployment list only your own names.
# ALLOWED_HOSTS = ["localhost", "127.0.0.1", "game.example.com"]

# Origins allowed to submit forms over HTTPS (scheme included), e.g. the
# public website address once it is behind TLS.
CSRF_TRUSTED_ORIGINS = [
    # "https://game.example.com",
]

# TLS is required for a public deployment; uncomment once HTTPS is in front.
# SESSION_COOKIE_SECURE = True
# CSRF_COOKIE_SECURE = True
# SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# The front proxy whose X-Forwarded-For header Evennia trusts. Set it to that
# proxy's address only, and have the proxy overwrite the header; see
# "Deployment notes (client addresses)" in README.md. Without it the
# approval page's same-address flag means nothing.
# UPSTREAM_IPS = ["<front proxy address>"]
