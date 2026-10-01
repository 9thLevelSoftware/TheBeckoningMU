"""
Tests for API URL routing configuration.

The endpoints must be routed and must answer with a deliberate response: the
data for a logged-in account, a refusal (401/403) for an anonymous one. A 404
means the route is missing; a 500 or any other code means the view broke.
"""

from django.test import Client, TestCase
from evennia.accounts.models import AccountDB

REFUSED = (401, 403)


class TestAPIRouting(TestCase):
    """Test that API endpoints are routed and answer callers deliberately."""

    def setUp(self):
        self.client = Client()

    def test_traits_api_endpoint_exists(self):
        """GET /api/traits/ refuses anonymous callers and serves logged-in ones."""
        response = self.client.get("/api/traits/")
        self.assertIn(response.status_code, REFUSED)

        account = AccountDB.objects.create_user(username="RouteUser", password="testpass123")
        self.client.force_login(account)
        response = self.client.get("/api/traits/")
        self.assertEqual(response.status_code, 200)

    def test_character_create_endpoint_exists(self):
        """An anonymous POST to the create endpoint is routed and refused."""
        response = self.client.post("/api/traits/character/create/")
        self.assertIn(response.status_code, REFUSED)
