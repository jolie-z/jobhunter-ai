from DrissionPage import ChromiumPage, ChromiumOptions
import time

port = 9224
co = ChromiumOptions()
co.set_local_port(port)
page = ChromiumPage(co)

# assuming page is currently on search results
sections = page.eles('tag:section')
print(f"Found {len(sections)} sections")

for item in sections[:3]:
    link_ele = item.ele('tag:a')
    if link_ele:
        href = link_ele.attr('href')
        print(f"href: {href}")
