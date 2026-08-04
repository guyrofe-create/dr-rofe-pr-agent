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
    def __init__(self, existing=False, member_ids=None):
        self.existing = existing
        self.member_ids = member_ids or ["member-123"]
        self.posts = []

    def get(self, url, **kwargs):
        if "/slugs/" in url:
            if self.existing:
                return Response({"post": {"id": "existing", "slug": "approved-slug"}})
            return Response(status_code=404)
        return Response(
            {"posts": [{"memberId": item} for item in self.member_ids]}
        )

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
        self.assertEqual(create["draftPost"]["memberId"], "member-123")

    def test_exact_configured_author_wins_over_discovery(self):
        configured_site = {**SITE, "member_id_env": "WIX_MEMBER"}
        with patch.dict(
            os.environ,
            {"WIX_API": "key", "WIX_SITE": "site", "WIX_MEMBER": "exact-author"},
        ):
            session = Session(member_ids=["other-author"])
            wix_blog.publish(
                configured_site,
                title="כותרת",
                html="<p>תוכן</p>",
                excerpt="תקציר",
                slug="approved-slug",
                expected_url="https://www.drguyrofe.com/post/approved-slug",
                session=session,
            )
        create = session.posts[1][1]["json"]
        self.assertEqual(create["draftPost"]["memberId"], "exact-author")

    def test_multiple_discovered_authors_require_exact_configuration(self):
        with patch.dict(os.environ, {"WIX_API": "key", "WIX_SITE": "site"}):
            with self.assertRaisesRegex(wix_blog.WixAPIError, "multiple"):
                wix_blog.publish(
                    SITE,
                    title="כותרת",
                    html="<p>תוכן</p>",
                    excerpt="תקציר",
                    slug="approved-slug",
                    expected_url="https://www.drguyrofe.com/post/approved-slug",
                    session=Session(member_ids=["author-a", "author-b"]),
                )

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
