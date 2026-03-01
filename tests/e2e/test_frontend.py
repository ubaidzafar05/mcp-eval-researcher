
import pytest


@pytest.mark.skip(reason="Requires running frontend server")
def test_frontend_flow(page):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    page.goto("http://localhost:3000")

    # Check title
    expect(page.locator("h1")).to_contain_text("Cloud Hive Research")

    # Submit query
    page.fill("textarea[name='query']", "Test Query")
    page.click("button[type='submit']")

    # Check stream logs appear
    expect(page.locator("text=connecting")).to_be_visible()
