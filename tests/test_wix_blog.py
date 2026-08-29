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
    def __init__(self, payload=None, status_code=200, headers=None):
        self.payload = payload or {}
        self.status_code = status_code
        self.headers = headers or {}

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

    def test_update_published_changes_exact_fields_and_verifies_redirect(self):
        class UpdateSession:
            def __init__(self):
                self.slug_calls = 0
                self.patch_payload = None

            def get(self, url, **kwargs):
                if "/slugs/" in url:
                    self.slug_calls += 1
                    if self.slug_calls == 1:
                        return Response({"post": {"id": "post-1", "title": "ישן"}})
                    if self.slug_calls == 2:
                        return Response(status_code=404)
                    return Response({"post": {"id": "post-1", "title": "חדש"}})
                return Response(status_code=301, headers={
                    "Location": "https://www.drguyrofe.com/post/new-slug"
                })

            def patch(self, url, **kwargs):
                self.patch_payload = kwargs["json"]
                return Response({"draftPost": {"id": "post-1"}})

            def post(self, url, **kwargs):
                return Response({"post": {"id": "post-1"}})

        with patch.dict(os.environ, {"WIX_API": "key", "WIX_SITE": "site"}):
            session = UpdateSession()
            result = wix_blog.update_published(
                SITE,
                old_slug="old-slug",
                expected_current_title="ישן",
                title="חדש",
                excerpt="תקציר מלא.",
                slug="new-slug",
                old_url="https://www.drguyrofe.com/post/old-slug",
                expected_url="https://www.drguyrofe.com/post/new-slug",
                session=session,
            )
        self.assertEqual(result["url"], "https://www.drguyrofe.com/post/new-slug")
        self.assertEqual(
            session.patch_payload["draftPost"],
            {
                "id": "post-1",
                "title": "חדש",
                "excerpt": "תקציר מלא.",
                "seoSlug": "new-slug",
            },
        )


if __name__ == "__main__":
    unittest.main()
