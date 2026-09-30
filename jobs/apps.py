"""
Django app configuration for the Jobs system.
"""

from django.apps import AppConfig


class JobsConfig(AppConfig):
    """
    Configuration for the Jobs app.
    """

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'jobs'
    label = 'jobs'
    verbose_name = 'Jobs System'
