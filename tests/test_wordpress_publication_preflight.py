import json
import unittest
from pathlib import Path

from scripts import wordpress_publication_preflight as preflight


class FakeResponse:
    def __init__(self, status, content_type, payload):
        self.status = status
        self.headers = {"Content-Type": content_type}
        self._body = (
            json.dumps(payload).encode("utf-8")
            if not isinstance(payload, bytes)
            else payload
        )

    def getcode(self):
        return self.status

    def read(self, _limit):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class WordPressPublicationPreflightTests(unittest.TestCase):
    def test_json_list_is_healthy_and_uses_read_only_get(self):
        requests = []

        def opener(request, timeout):
            requests.append((request, timeout))
            return FakeResponse(200, "application/json; charset=UTF-8", [])

        healthy, detail = preflight.check(
            "https://guyrofe.com", opener=opener, timeout=7
        )

        self.assertTrue(healthy)
        self.assertIn("HTTP 200", detail)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0][0].method, "GET")
        self.assertIn("slug=reputation-agent-read-only-preflight", requests[0][0].full_url)
        self.assertEqual(requests[0][1], 7)

    def test_html_202_is_deferred_across_all_read_only_routes(self):
        requests = []

        def opener(request, timeout):
            requests.append(request)
            return FakeResponse(202, "text/html", b"challenge")

        healthy, detail = preflight.check("https://guyrofe.com", opener=opener)

        self.assertFalse(healthy)
        self.assertEqual(len(requests), 3)
        self.assertEqual(detail.count("HTTP 202 text/html"), 3)
        self.assertTrue(all(request.method == "GET" for request in requests))

    def test_workflow_checks_gateway_before_consuming_dashboard_queue(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "publish_approved.yml"
        ).read_text(encoding="utf-8")
        preflight_step = workflow.index(
            "Check WordPress publication gateway without consuming approval"
        )
        queue_step = workflow.index("Check dashboard approval queue")
        self.assertLess(preflight_step, queue_step)
        self.assertIn("steps.wordpress_preflight.outputs.ready != 'false'", workflow)
        self.assertIn("approval queue remains untouched", workflow)


if __name__ == "__main__":
    unittest.main()
