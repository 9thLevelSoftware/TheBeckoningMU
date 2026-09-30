"""
Boons Django app configuration.
"""

from django.apps import AppConfig


class BoonsConfig(AppConfig):
    """Django app configuration for the Boons system."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'boons'
    label = 'boons'
    verbose_name = 'Boons System'
