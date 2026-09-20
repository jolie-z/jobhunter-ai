from DrissionPage import ChromiumOptions, ChromiumPage
import time

_co = ChromiumOptions()
_co.set_address('127.0.0.1:19222')

try:
    page = ChromiumPage(addr_or_opts=_co)
    print("Page title:", page.title)
    print("Page URL:", page.url)
    
    # Try finding job cards
    cards = page.eles('.job-card-wrapper')
    print("Found cards:", len(cards))
    
    if len(cards) == 0:
        # print first 500 chars of body to see what's wrong
        print("Body preview:", page.html[:500])
except Exception as e:
    print("Error:", e)
