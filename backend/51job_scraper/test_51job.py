from playwright.sync_api import sync_playwright

def test():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        # I need a sample 51job url
        page.goto("https://we.51job.com/pc/search?keyword=AI%20Agent&jobArea=030200", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        
        # Click the first job link
        first_job = page.locator('.joblist-item').first
        if first_job.count() > 0:
            job_url = first_job.get_attribute('href')
            if not job_url.startswith('http'):
                job_url = 'https://we.51job.com' + job_url
            print("Job URL:", job_url)
            
            page.goto(job_url, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            
            html = page.content()
            print("Title:", page.title())
            
            # try to get map address
            loc1 = page.locator("p.fp:has-text('上班地址')")
            print("Loc1 text:", loc1.inner_text() if loc1.count() > 0 else "None")
            
            # Look for the new address text
            loc2 = page.locator("*:has-text('地图完整地址')").last
            print("Loc2 text:", loc2.inner_text() if loc2.count() > 0 else "None")
            
            # Or get the generic address container
            addr_container = page.locator(".bmsg.inbox").last
            if addr_container.count() > 0:
                print("Container text:", addr_container.inner_text()[:200])

        browser.close()

test()
