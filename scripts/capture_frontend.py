#!/usr/bin/env python3
"""
Frontend Full-Page Screenshot Tool using Playwright
Usage:
    python scripts/capture_frontend.py --all
    python scripts/capture_frontend.py --url http://localhost:3000/strategy --output screenshots/strategy.png
"""

import os
import sys
import time
import argparse
from playwright.sync_api import sync_playwright

DEFAULT_PAGES = {
    "home": "http://localhost:3000",
    "strategy": "http://localhost:3000/strategy",
    "analytics": "http://localhost:3000/analytics",
    "resume_editor": "http://localhost:3000/resume-editor",
    "command_center": "http://localhost:3000/prototype/command-center",
}

def capture(url: str, output_path: str, width: int = 1440, height: int = 900, delay: float = 1.5, full_page: bool = True):
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with sync_playwright() as p:
        try:
            # Prefer system chrome if available, fallback to chromium
            browser = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True)
            
        page = browser.new_page(
            viewport={"width": width, "height": height},
            device_scale_factor=2  # Retina 2x for crisp text & charts
        )
        print(f"[*] Navigating to {url} ...")
        page.goto(url, wait_until="load", timeout=20000)
        
        if delay > 0:
            time.sleep(delay)
            
        print(f"[*] Capturing screenshot (full_page={full_page}) -> {output_path}")
        page.screenshot(path=output_path, full_page=full_page)
        browser.close()
        print(f"[✓] Successfully saved to {output_path}")

def main():
    parser = argparse.ArgumentParser(description="Capture full-page screenshots of frontend pages")
    parser.add_argument("--all", action="store_true", help="Capture all preset frontend pages")
    parser.add_argument("--url", type=str, default=None, help="Specific URL to capture")
    parser.add_argument("--output", type=str, default=None, help="Output image file path")
    parser.add_argument("--outdir", type=str, default="screenshots", help="Directory to save preset screenshots")
    parser.add_argument("--delay", type=float, default=1.5, help="Wait time in seconds after page load before capture")
    parser.add_argument("--width", type=int, default=1440, help="Viewport width")
    parser.add_argument("--height", type=int, default=900, help="Viewport height")
    parser.add_argument("--no-full", action="store_true", help="Disable full page capture (capture viewport only)")

    args = parser.parse_args()

    full_page = not args.no_full

    if args.url:
        out = args.output or os.path.join(args.outdir, "page.png")
        capture(args.url, out, width=args.width, height=args.height, delay=args.delay, full_page=full_page)
    elif args.all or not sys.argv[1:]:
        print(f"[*] Capturing all {len(DEFAULT_PAGES)} frontend preset pages...")
        for name, url in DEFAULT_PAGES.items():
            out = os.path.join(args.outdir, f"{name}.png")
            try:
                capture(url, out, width=args.width, height=args.height, delay=args.delay, full_page=full_page)
            except Exception as err:
                print(f"[!] Error capturing {name} ({url}): {err}")
        print("[✓] All screenshots captured successfully.")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
