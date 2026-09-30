"""
Status Django app configuration.
"""

from django.apps import AppConfig


class StatusConfig(AppConfig):
    """Django app configuration for the Status system."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'status'
    label = 'status'
    verbose_name = 'Status System'
