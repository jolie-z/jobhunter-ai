"""PDF rendering utilities using headless Chromium (via Playwright).

Migrated and simplified from Resume-Matcher project.
Core idea: backend does NOT render HTML — it only launches a headless browser,
visits the frontend's /print/resume page, and calls page.pdf().
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from playwright.async_api import (
    Browser,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import (
    Error as PlaywrightError,
)

# renderer 关闭限时（秒）：防 driver 僵死阻塞应用/测试进程退出
_CLOSE_TIMEOUT_S = 8

logger = logging.getLogger("pdf_renderer")

# Navigation timeout: 60s covers slow cold-start renders
_NAV_TIMEOUT_MS = 60_000


class PDFRenderError(Exception):
    """Custom exception for PDF rendering errors with helpful messages."""
    pass


# ---------------------------------------------------------------------------
# Singleton browser management
# ---------------------------------------------------------------------------
_playwright: Playwright | None = None
_browser: Browser | None = None
_init_lock = asyncio.Lock()


def _browser_is_healthy(browser: Browser | None) -> bool:
    """Return whether a cached browser can still accept new pages/contexts."""
    if browser is None:
        return False
    try:
        return browser.is_connected()
    except Exception:
        return False


def _is_browser_closed_error(error: BaseException) -> bool:
    """Identify Playwright failures recoverable by recreating Chromium."""
    message = str(error).lower()
    return "browser has been closed" in message or "target page, context or browser has been closed" in message


async def _close_pdf_renderer_unlocked() -> None:
    """Dispose renderer resources; caller must hold _init_lock when needed."""
    global _playwright, _browser

    browser = _browser
    playwright = _playwright
    _browser = None
    _playwright = None

    if browser:
        try:
            await asyncio.wait_for(browser.close(), timeout=_CLOSE_TIMEOUT_S)
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ Playwright browser.close() 超时（{_CLOSE_TIMEOUT_S}s），跳过优雅关闭")
        except Exception as e:
            logger.debug(f"Ignored error while closing browser: {e}")
    if playwright is not None:
        try:
            await asyncio.wait_for(playwright.stop(), timeout=_CLOSE_TIMEOUT_S)
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ Playwright stop() 超时（{_CLOSE_TIMEOUT_S}s），跳过，交由进程退出回收")


async def init_pdf_renderer(force: bool = False) -> None:
    """Initialize a healthy Playwright browser instance (singleton, thread-safe)."""
    global _playwright, _browser

    if not force and _browser_is_healthy(_browser):
        return

    async with _init_lock:
        if not force and _browser_is_healthy(_browser):
            return
        if _browser is not None or _playwright is not None:
            await _close_pdf_renderer_unlocked()
        logger.info("🚀 Initializing Playwright PDF renderer...")
        _playwright = await async_playwright().start()
        _browser = await _launch_browser(_playwright)
        logger.info("✅ Playwright PDF renderer ready.")


async def close_pdf_renderer() -> None:
    """Close the Playwright browser instance.

    关闭全程限时：driver 僵死时 browser.close()/playwright.stop() 会无限等待，
    阻塞整个 shutdown 链路（曾致全量回归跑完 100% 后进程假死、CI 超时）。
    超时即放弃优雅关闭，driver 子进程随进程退出回收（stdin 管道关闭后 node 进程自尽）。
    """
    async with _init_lock:
        had_resources = _browser is not None or _playwright is not None
        await _close_pdf_renderer_unlocked()
        if had_resources:
            logger.info("🔒 Playwright browser closed.")


async def _new_page_with_retry() -> Page:
    """Create a page, rebuilding Chromium once if the cached instance died."""
    for attempt in range(2):
        await init_pdf_renderer()
        browser = _browser
        if browser is None:
            raise PDFRenderError("PDF renderer failed to initialize.")
        try:
            return await browser.new_page()
        except PlaywrightError as e:
            if attempt == 0 and _is_browser_closed_error(e):
                logger.warning("⚠️ Playwright browser 已失效，正在自动重建 PDF 渲染器")
                await init_pdf_renderer(force=True)
                continue
            raise
    raise PDFRenderError("PDF renderer failed to create a page.")


async def _new_context_with_retry(**kwargs):
    """Create a browser context, rebuilding Chromium once if needed."""
    for attempt in range(2):
        await init_pdf_renderer()
        browser = _browser
        if browser is None:
            raise PDFRenderError("PDF renderer failed to initialize.")
        try:
            return await browser.new_context(**kwargs)
        except PlaywrightError as e:
            if attempt == 0 and _is_browser_closed_error(e):
                logger.warning("⚠️ Playwright browser 已失效，正在自动重建图片渲染器")
                await init_pdf_renderer(force=True)
                continue
            raise
    raise PDFRenderError("PDF renderer failed to create a context.")


# ---------------------------------------------------------------------------
# Browser launch helpers
# ---------------------------------------------------------------------------
def _find_chromium_executable() -> str | None:
    """Find system Chrome/Chromium executable (macOS focus)."""
    if sys.platform == "darwin":
        candidates = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        ]
    elif sys.platform == "win32":
        candidates = [
            Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
            / "Google/Chrome/Application/chrome.exe",
        ]
    else:
        candidates = [
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/google-chrome-stable"),
            Path("/usr/bin/chromium"),
            Path("/usr/bin/chromium-browser"),
        ]

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


async def _launch_browser(playwright: Playwright) -> Browser:
    """Launch Chromium, falling back to system Chrome if Playwright's isn't installed."""
    try:
        return await playwright.chromium.launch()
    except PlaywrightError as e:
        if "Executable doesn't exist" not in str(e):
            raise
        fallback = _find_chromium_executable()
        if not fallback:
            raise PDFRenderError(
                "Playwright browser executable is missing, and no system Chrome/Edge "
                "installation was found. Run: python -m playwright install chromium"
            ) from e
        logger.info(f"Using system browser: {fallback}")
        return await playwright.chromium.launch(executable_path=fallback)


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------
def _resolve_pdf_margins(margins: dict | None) -> dict:
    """Convert margin dict (mm integers) to Playwright format strings."""
    if margins:
        return {
            "top": f"{margins.get('top', 10)}mm",
            "right": f"{margins.get('right', 10)}mm",
            "bottom": f"{margins.get('bottom', 10)}mm",
            "left": f"{margins.get('left', 10)}mm",
        }
    return {"top": "10mm", "right": "10mm", "bottom": "10mm", "left": "10mm"}


async def render_resume_pdf(
    url: str,
    page_size: str = "A4",
    selector: str = ".resume-print",
    margins: dict | None = None,
) -> bytes:
    """Render a URL to PDF bytes.

    Args:
        url: The URL to render (print route on frontend)
        page_size: "A4" or "Letter"
        selector: CSS selector to wait for before rendering
        margins: Page margins dict with top/right/bottom/left in mm

    Returns:
        PDF file content as bytes
    """
    pdf_format = "A4" if page_size.upper() == "A4" else "Letter"
    pdf_margins = _resolve_pdf_margins(margins)

    page: Page = await _new_page_with_retry()
    try:
        logger.info(f"📄 Rendering PDF from: {url}")
        # Use wait_until="load" — NOT "networkidle" (Next.js HMR keeps network busy)
        await page.goto(url, wait_until="load", timeout=_NAV_TIMEOUT_MS)
        await page.wait_for_selector(selector, timeout=_NAV_TIMEOUT_MS)
        # Wait for fonts to load
        await page.wait_for_function(
            "() => document.fonts.ready.then(() => true)", timeout=_NAV_TIMEOUT_MS
        )

        # 🌟 彻底清除控制台、悬浮调试图标与任何固定定位干扰元素，防止截入 PDF
        await page.evaluate("""
            () => {
                const devBadges = document.querySelectorAll('nextjs-portal, #__next-build-watcher, [data-nextjs-toast], [data-nextjs-dialog], .nextjs-static-indicator-toast-wrapper, [data-terminal-drawer]');
                devBadges.forEach(el => el.remove());
            }
        """)
        await page.add_style_tag(content="""
            nextjs-portal, #__next-build-watcher, [data-nextjs-toast], [data-nextjs-dialog], .nextjs-static-indicator-toast-wrapper, [data-terminal-drawer], .print\\:hidden {
                display: none !important;
                visibility: hidden !important;
                opacity: 0 !important;
            }
        """)

        pdf_bytes = await page.pdf(
            format=pdf_format,
            print_background=True,
            margin=pdf_margins,
        )
        logger.info(f"✅ PDF rendered successfully, size: {len(pdf_bytes)} bytes")
        return pdf_bytes
    except PlaywrightError as e:
        error_msg = str(e)
        if "net::ERR_CONNECTION_REFUSED" in error_msg:
            raise PDFRenderError(
                f"Cannot connect to frontend for PDF generation. "
                f"Attempted URL: {url}. "
                f"Please ensure the frontend is running on the correct port."
            ) from e
        logger.error(f"PDF rendering failed for {url}: {error_msg}")
        raise PDFRenderError("PDF rendering failed. Please try again.") from e
    finally:
        await page.close()


async def render_resume_image(
    url: str,
    selector: str = ".resume-print",
) -> bytes:
    """Render a URL to a full-page image (JPEG) bytes.

    Args:
        url: The URL to render (print route on frontend)
        selector: CSS selector to wait for before rendering

    Returns:
        Image file content as bytes
    """
    context = await _new_context_with_retry(
        device_scale_factor=2,
        viewport={"width": 800, "height": 1200}
    )
    page: Page = await context.new_page()
    try:
        logger.info(f"📸 Rendering Image from: {url}")
        # Use wait_until="load"
        await page.goto(url, wait_until="load", timeout=_NAV_TIMEOUT_MS)
        resume_el = await page.wait_for_selector(selector, timeout=_NAV_TIMEOUT_MS)
        # Wait for fonts to load
        await page.wait_for_function(
            "() => document.fonts.ready.then(() => true)", timeout=_NAV_TIMEOUT_MS
        )

        # 🌟 彻底清除 Next.js 开发环境注入的悬浮调试图标 (白色 N 图标/Portal) 与控制台等干扰元素
        await page.evaluate("""
            () => {
                const devBadges = document.querySelectorAll('nextjs-portal, #__next-build-watcher, [data-nextjs-toast], [data-nextjs-dialog], .nextjs-static-indicator-toast-wrapper, [data-terminal-drawer]');
                devBadges.forEach(el => el.remove());
            }
        """)
        await page.add_style_tag(content="""
            nextjs-portal, #__next-build-watcher, [data-nextjs-toast], [data-nextjs-dialog], .nextjs-static-indicator-toast-wrapper, [data-terminal-drawer], .print\\:hidden {
                display: none !important;
                visibility: hidden !important;
                opacity: 0 !important;
            }
        """)

        # Ensure animations are done by waiting a tiny bit
        await asyncio.sleep(0.5)

        # 🌟 严格只截取简历正文 DOM 容器（避免全屏截取带入外部悬浮物或多余空白）
        image_bytes = await resume_el.screenshot(
            type="jpeg",
            quality=85,
        )

        # 🌟 若体积仍超过 1.2MB，使用 PIL 自动优化压缩，保障 BOSS 聊天 OSS 上传秒级送达
        if len(image_bytes) > 1.2 * 1024 * 1024:
            try:
                import io

                from PIL import Image
                img = Image.open(io.BytesIO(image_bytes))
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=80, optimize=True)
                image_bytes = buf.getvalue()
                logger.info(f"🗜️ Image optimized to {len(image_bytes)} bytes")
            except Exception as comp_err:
                logger.warning(f"Image compression fallback: {comp_err}")

        logger.info(f"✅ Image rendered successfully, size: {len(image_bytes)} bytes")
        return image_bytes
    except PlaywrightError as e:
        error_msg = str(e)
        if "net::ERR_CONNECTION_REFUSED" in error_msg:
            raise PDFRenderError(
                f"Cannot connect to frontend for Image generation. "
                f"Attempted URL: {url}. "
                f"Please ensure the frontend is running on the correct port."
            ) from e
        logger.error(f"Image rendering failed for {url}: {error_msg}")
        raise PDFRenderError("Image rendering failed. Please try again.") from e
    finally:
        await page.close()
        await context.close()


async def render_html_to_pdf(
    html_content: str,
    page_size: str = "A4",
    margins: dict | None = None,
) -> bytes:
    """Render raw HTML content directly to PDF bytes (zero network/server dependency)."""
    context = await _new_context_with_retry()
    page: Page = await context.new_page()
    try:
        await page.set_content(html_content, wait_until="load", timeout=15000)
        # Wait for fonts to be ready
        try:
            await page.wait_for_function("() => document.fonts.ready.then(() => true)", timeout=5000)
        except Exception:
            pass
        pdf_margins = _resolve_pdf_margins(margins) if margins else {"top": "8mm", "right": "12mm", "bottom": "10mm", "left": "12mm"}
        pdf_bytes = await page.pdf(
            format=page_size,
            print_background=True,
            margin=pdf_margins,
        )
        return pdf_bytes
    finally:
        await page.close()
        await context.close()


async def render_html_to_image(
    html_content: str,
    selector: str = ".resume-container",
) -> bytes:
    """Render raw HTML content directly to JPEG image bytes (zero network/server dependency)."""
    context = await _new_context_with_retry(
        device_scale_factor=2,
        viewport={"width": 800, "height": 1200}
    )
    page: Page = await context.new_page()
    try:
        await page.set_content(html_content, wait_until="load", timeout=15000)
        resume_el = await page.wait_for_selector(selector, timeout=10000)
        image_bytes = await resume_el.screenshot(
            type="jpeg",
            quality=85,
        )
        if len(image_bytes) > 1.2 * 1024 * 1024:
            try:
                import io

                from PIL import Image
                img = Image.open(io.BytesIO(image_bytes))
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=80, optimize=True)
                image_bytes = buf.getvalue()
            except Exception as comp_err:
                logger.warning(f"Image compression fallback: {comp_err}")
        return image_bytes
    finally:
        await page.close()
        await context.close()
