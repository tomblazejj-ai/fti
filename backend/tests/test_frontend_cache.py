"""The app window must load a new build at the next open (8. 11. 2026: it kept an old index.html without the new card)."""

import re

import pytest
from fastapi.testclient import TestClient

from app.main import FRONTEND_DIST, app


@pytest.mark.skipif(not (FRONTEND_DIST / "index.html").is_file(), reason="frontend not built")
def test_page_is_revalidated_but_hashed_assets_may_be_cached():
    c = TestClient(app)
    page = c.get("/")
    assert page.status_code == 200 and page.headers["cache-control"] == "no-cache"
    asset = re.search(r'/assets/[^"]+\.js', page.text)
    if asset:
        assert "cache-control" not in c.get(asset.group(0)).headers
