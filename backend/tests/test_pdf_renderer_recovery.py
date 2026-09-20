from types import SimpleNamespace

import pytest
from playwright.async_api import Error as PlaywrightError

from app.core import pdf_renderer


class FakeBrowser:
    def __init__(self, connected: bool = True, page_error: Exception | None = None):
        self.connected = connected
        self.page_error = page_error
        self.closed = False
        self.new_page_calls = 0

    def is_connected(self) -> bool:
        return self.connected and not self.closed

    async def close(self) -> None:
        self.closed = True

    async def new_page(self):
        self.new_page_calls += 1
        if self.page_error:
            error = self.page_error
            self.page_error = None
            raise error
        return SimpleNamespace()


class FakePlaywright:
    def __init__(self):
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


@pytest.fixture(autouse=True)
async def reset_renderer_state():
    await pdf_renderer.close_pdf_renderer()
    yield
    await pdf_renderer.close_pdf_renderer()


@pytest.mark.anyio
async def test_init_replaces_a_closed_cached_browser(monkeypatch):
    old_browser = FakeBrowser(connected=False)
    old_playwright = FakePlaywright()
    new_browser = FakeBrowser()
    new_playwright = FakePlaywright()

    async def fake_start():
        return new_playwright

    async def fake_launch(_playwright):
        return new_browser

    monkeypatch.setattr(pdf_renderer, "async_playwright", lambda: SimpleNamespace(start=fake_start))
    monkeypatch.setattr(pdf_renderer, "_launch_browser", fake_launch)
    pdf_renderer._browser = old_browser
    pdf_renderer._playwright = old_playwright

    await pdf_renderer.init_pdf_renderer()

    assert pdf_renderer._browser is new_browser
    assert old_browser.closed
    assert old_playwright.stopped


@pytest.mark.anyio
async def test_new_page_rebuilds_renderer_after_playwright_closed_error(monkeypatch):
    stale_browser = FakeBrowser(
        page_error=PlaywrightError("Target page, context or browser has been closed")
    )
    fresh_browser = FakeBrowser()
    fresh_playwright = FakePlaywright()
    launch_count = 0

    async def fake_start():
        return fresh_playwright

    async def fake_launch(_playwright):
        nonlocal launch_count
        launch_count += 1
        return fresh_browser

    monkeypatch.setattr(pdf_renderer, "async_playwright", lambda: SimpleNamespace(start=fake_start))
    monkeypatch.setattr(pdf_renderer, "_launch_browser", fake_launch)
    pdf_renderer._browser = stale_browser
    pdf_renderer._playwright = FakePlaywright()

    page = await pdf_renderer._new_page_with_retry()

    assert page is not None
    assert stale_browser.new_page_calls == 1
    assert pdf_renderer._browser is fresh_browser
    assert launch_count == 1
