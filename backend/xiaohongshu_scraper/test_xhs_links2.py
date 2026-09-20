from DrissionPage import ChromiumPage, ChromiumOptions
import time

port = 9224
co = ChromiumOptions()
co.set_local_port(port)
page = ChromiumPage(co)

# Print outerHTML of the first section to inspect raw DOM
section = page.ele('tag:section')
print(section.html)
