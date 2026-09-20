#!/usr/bin/env python3
"""渲染 docs/architecture-overview.svg → docs/architecture-overview.png（2x 高清）

用法: cd backend && .venv/bin/python ../scripts/render_architecture.py
"""
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "docs" / "architecture-overview.svg"
PNG = ROOT / "docs" / "architecture-overview.png"

svg_text = SVG.read_text(encoding="utf-8")
html = f"""<!doctype html>
<html><body style="margin:0;background:#fff">{svg_text}</body></html>"""

with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
    f.write(html)
    tmp = Path(f.name)

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1300, "height": 1000}, device_scale_factor=2)
        page.goto(tmp.as_uri())
        page.locator("svg").first.screenshot(path=str(PNG))
        browser.close()
finally:
    tmp.unlink()

print(f"✅ 已渲染 {PNG}")
