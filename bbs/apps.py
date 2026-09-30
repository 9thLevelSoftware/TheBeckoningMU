"""
BBS Django app configuration.
"""

from django.apps import AppConfig


class BbsConfig(AppConfig):
    """Django app configuration for the BBS system."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bbs'
    label = 'bbs'
    verbose_name = 'Bulletin Board System'
