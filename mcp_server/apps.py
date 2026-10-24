from django.apps import AppConfig


class MCPServerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mcp_server"
    verbose_name = "MCP companion"

    def ready(self):
        from . import signals  # noqa: F401
