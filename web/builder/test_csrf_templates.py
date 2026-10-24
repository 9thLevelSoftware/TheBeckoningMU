"""Rendered builder tokens work with deployment-specific CSRF cookie names."""

import json
import re

from django.test import Client, override_settings
from django.urls import reverse

from web.builder.tests import BuilderGateTestBase


@override_settings(CSRF_COOKIE_NAME="acceptance_csrf")
class BuilderTemplateCSRFTests(BuilderGateTestBase):
    def rendered_token(self, client, route):
        response = client.get(reverse(route))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        match = re.search(r"const csrftoken = '([A-Za-z0-9]+)';", html)
        self.assertIsNotNone(match, "AJAX must use the rendered token, independent of the CSRF cookie name")
        self.assertNotIn("getCookie('csrftoken')", html)
        self.assertIn("acceptance_csrf", client.cookies)
        self.assertNotIn("csrftoken", client.cookies)
        return match.group(1)

    def test_nondefault_cookie_submission_and_independent_review_keep_csrf_enforced(self):
        project = self.make_project(self.owner)
        owner_client = Client(enforce_csrf_checks=True)
        owner_client.force_login(self.owner)
        token = self.rendered_token(owner_client, "builder:dashboard")
        submit_url = reverse("builder:submit_project", args=[project.pk])
        payload = json.dumps(
            {"connection_room_id": self.room.pk, "connection_direction": "n", "notes": "Review please"}
        )
        self.assertEqual(owner_client.post(submit_url, payload, content_type="application/json").status_code, 403)
        response = owner_client.post(submit_url, payload, content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200, response.content)
        project.refresh_from_db()
        self.assertEqual(project.status, "submitted")

        reviewer_client = Client(enforce_csrf_checks=True)
        reviewer_client.force_login(self.builder2)
        review_token = self.rendered_token(reviewer_client, "builder:build_review")
        approve_url = reverse("builder:approve_project", args=[project.pk])
        review_payload = json.dumps({"version": project.version})
        self.assertEqual(
            reviewer_client.post(approve_url, review_payload, content_type="application/json").status_code, 403
        )
        response = reviewer_client.post(
            approve_url, review_payload, content_type="application/json", HTTP_X_CSRFTOKEN=review_token
        )
        self.assertEqual(response.status_code, 200, response.content)
        project.refresh_from_db()
        self.assertEqual(project.status, "approved")
        self.assertEqual(project.reviewed_by_id, self.builder2.pk)
