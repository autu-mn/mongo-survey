"""前端页面路由：每个页面路径都能返回 HTML，静态资源可访问。"""

import pytest

from app.main import PAGE_ROUTES


@pytest.mark.parametrize("path", [
    p.replace("{survey_id}", "abc").replace("{slug}", "xyz")
    .replace("{response_id}", "r1").replace("{bank_id}", "b1").replace("{item_id}", "i1")
    for p in PAGE_ROUTES
])
def test_page_routes_serve_html(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")


@pytest.mark.parametrize("asset", ["app.css", "api.js", "editor.js", "fill.js",
                                   "bank-pages.js", "question-form.js", "question-item.js"])
def test_static_assets(client, asset):
    assert client.get(f"/static/{asset}").status_code == 200
