import asyncio
from playwright.async_api import async_playwright
import os

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

async def convert_svg_to_png():
    svg_path = os.path.join(_REPO_ROOT, "docs/architecture-overview.svg")
    png_path = os.path.join(_REPO_ROOT, "docs/architecture-overview.png")
    png_v2_path = os.path.join(_REPO_ROOT, "docs/architecture/jobhunter_architecture_v2.png")
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ margin: 0; padding: 0; background: #F8FAFC; overflow: hidden; }}
      </style>
    </head>
    <body>
      <img src="file://{svg_path}" width="1440" height="1020" style="display:block;" />
    </body>
    </html>
    """
    temp_html = os.path.join(_REPO_ROOT, "scripts", "temp_render.html")
    with open(temp_html, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 1020}, device_scale_factor=2)
        await page.goto(f"file://{temp_html}")
        await page.wait_for_timeout(1000)
        await page.screenshot(path=png_path, full_page=True)
        await page.screenshot(path=png_v2_path, full_page=True)
        await browser.close()
        
    if os.path.exists(temp_html):
        os.remove(temp_html)
    print(f"Rendered PNG successfully to {png_path} and {png_v2_path}")

if __name__ == "__main__":
    asyncio.run(convert_svg_to_png())
