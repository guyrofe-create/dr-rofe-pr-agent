import os
import unittest
from unittest.mock import patch

from scripts import wix_blog


SITE = {
    "key": "DRGUYROFE_COM",
    "base_url": "https://www.drguyrofe.com",
    "post_route": "post",
    "api_key_env": "WIX_API",
    "site_id_env": "WIX_SITE",
}


class Response:
    def __init__(self, payload=None, status_code=200):
        self.payload = payload or {}
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class Session:
    def __init__(self, existing=False):
        self.existing = existing
        self.posts = []

    def get(self, url, **kwargs):
        if self.existing:
            return Response({"post": {"id": "existing", "slug": "approved-slug"}})
        return Response(status_code=404)

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        if "/ricos/" in url:
            return Response({"document": {"nodes": [{"type": "PARAGRAPH"}]}})
        return Response({"draftPost": {"id": "created"}})


class WixBlogTests(unittest.TestCase):
    def test_existing_slug_is_idempotent(self):
        with patch.dict(os.environ, {"WIX_API": "key", "WIX_SITE": "site"}):
            session = Session(existing=True)
            url = wix_blog.publish(
                SITE,
                title="כותרת",
                html="<p>תוכן</p>",
                excerpt="תקציר",
                slug="approved-slug",
                expected_url="https://www.drguyrofe.com/post/approved-slug",
                session=session,
            )
        self.assertEqual(url, "https://www.drguyrofe.com/post/approved-slug")
        self.assertEqual(session.posts, [])

    def test_new_post_converts_to_ricos_and_publishes(self):
        with patch.dict(os.environ, {"WIX_API": "key", "WIX_SITE": "site"}):
            session = Session()
            url = wix_blog.publish(
                SITE,
                title="כותרת",
                html='<p>תוכן עם <a href="https://who.int">מקור</a></p>',
                excerpt="תקציר",
                slug="approved-slug",
                expected_url="https://www.drguyrofe.com/post/approved-slug",
                session=session,
            )
        self.assertEqual(url, "https://www.drguyrofe.com/post/approved-slug")
        self.assertEqual(len(session.posts), 2)
        create = session.posts[1][1]["json"]
        self.assertTrue(create["publish"])
        self.assertEqual(create["draftPost"]["seoSlug"], "approved-slug")

    def test_approved_url_must_match_site_route(self):
        with patch.dict(os.environ, {"WIX_API": "key", "WIX_SITE": "site"}):
            with self.assertRaises(PermissionError):
                wix_blog.publish(
                    SITE,
                    title="כותרת",
                    html="<p>תוכן</p>",
                    excerpt="תקציר",
                    slug="approved-slug",
                    expected_url="https://other.example/post/approved-slug",
                    session=Session(),
                )


if __name__ == "__main__":
    unittest.main()
