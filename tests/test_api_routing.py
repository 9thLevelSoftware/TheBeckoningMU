"""
Tests for API URL routing configuration.
Ensures web character creation endpoints are properly wired up.
"""
from django.test import TestCase, Client
from django.urls import reverse


class TestAPIRouting(TestCase):
    """Test that API endpoints are accessible through URL routing."""

    def setUp(self):
        """Set up test client."""
        self.client = Client()

    def test_traits_api_endpoint_exists(self):
        """Test that /api/traits/ endpoint is accessible"""
        response = self.client.get('/api/traits/')
        # Should get 200 or 401 (if auth required), not 404
        self.assertNotEqual(response.status_code, 404,
                           msg="API endpoint /api/traits/ returns 404 - URL routing not configured")

    def test_character_create_endpoint_exists(self):
        """Test that character creation endpoint exists"""
        response = self.client.post('/api/traits/character/create/')
        # Should get 400 (bad request) or 401, not 404
        self.assertNotEqual(response.status_code, 404,
                           msg="API endpoint /api/traits/character/create/ returns 404 - URL routing not configured")
