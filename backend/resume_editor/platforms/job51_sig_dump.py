#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dump resumeApi 中回写相关方法的源码，标定参数顺序（只读）"""

import json
import os
import sys
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
from browser_common import connect_page, get_platform_port

PORT = get_platform_port("51job")
RESUME_URL = "https://www.51job.com/resume/center"

METHODS = [
    "addWorkExp", "delWorkExp",
    "getProjectAdd", "getProjectDel",
    "addEducation", "delEducation",
    "addIntention", "delIntention",
    "getSkillItAdd", "getSkillItDel",
    "languageAdd", "languageDel",
    "getCertificateEdit", "getCertificateDel", "multiEditCertification",
    "editSelfIntroduction", "editIntention",
]

JS = r"""
return (function() {
    var nuxt = document.querySelector('#__nuxt') || document.querySelector('#app');
    if (!nuxt || !nuxt.__vue__) return JSON.stringify({error: 'no vue'});
    var ra = nuxt.__vue__.$api.resumeApi;
    var out = {};
    METHODS.forEach(function(m) {
        out[m] = ra[m] ? ra[m].toString() : '__MISSING__';
    });
    return JSON.stringify(out);
})();
""".replace("METHODS", json.dumps(METHODS))


def main():
    page = connect_page(PORT)
    tab = page.latest_tab
    if "resume/center" not in tab.url:
        tab.get(RESUME_URL)
        time.sleep(8)
    data = json.loads(tab.run_js(JS))
    for m, src in data.items():
        print(f"--- {m} ---")
        print(src[:600])
        print()
    out_path = os.path.join(os.path.dirname(_SCRIPT_DIR), "data", "51job_api_sigs.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"已保存: {out_path}")


if __name__ == "__main__":
    main()
