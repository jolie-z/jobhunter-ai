#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""智联招聘回写 API 探针（只读）：dump Vuex resume 模块的 actions/mutations 处理器源码，
定位各模块（工作经历/项目/教育/技能/语言/证书/自我评价/求职意向）的保存端点"""

import json
import os
import sys
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
from browser_common import connect_page, get_platform_port

PORT = get_platform_port("zhilian")
RESUME_URL = "https://i.zhaopin.com/resume"

JS = r"""
return (function() {
    var root = document.querySelector('#root') || document.querySelector('#app');
    if (!root || !root.__vue__) return JSON.stringify({error: 'no vue'});
    var store = root.__vue__.$store;
    if (!store || !store.state || !store.state.resume) return JSON.stringify({error: 'no resume store'});
    var out = {stateKeys: Object.keys(store.state.resume), crKeys: []};
    var cr = store.state.resume.currentResume;
    if (cr) out.crKeys = Object.keys(cr);
    // actions：名称含保存语义的，dump 处理器源码
    out.actions = {};
    Object.keys(store._actions || {}).forEach(function(k) {
        if (/resume|work|edu|pro|skill|lang|cert|train|intention|desire|save|update|add|del|edit|eval/i.test(k)) {
            out.actions[k] = (store._actions[k] || []).map(function(fn) { return fn.toString().slice(0, 1500); });
        }
    });
    out.actionNames = Object.keys(store._actions || {});
    out.mutationNames = Object.keys(store._mutations || {});
    return JSON.stringify(out);
})();
"""


def main():
    page = connect_page(PORT)
    tab = page.latest_tab
    if "i.zhaopin.com/resume" not in tab.url:
        tab.get(RESUME_URL)
        time.sleep(8)
    raw = tab.run_js(JS)
    data = json.loads(raw)
    if "error" in data:
        print("ERROR:", data["error"])
        return
    print("state keys:", data.get("stateKeys"))
    print("currentResume keys:", data.get("crKeys"))
    print("\n=== ALL ACTIONS ===")
    print(data.get("actionNames"))
    print("\n=== ALL MUTATIONS ===")
    print(data.get("mutationNames"))
    print("\n=== MATCHED ACTION SOURCES ===")
    for name, fns in sorted(data.get("actions", {}).items()):
        print(f"--- {name} ---")
        for fn in fns:
            print(fn[:1200])
        print()
    out_path = os.path.join(os.path.dirname(_SCRIPT_DIR), "data", "zhilian_api_sigs.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"已保存: {out_path}")


if __name__ == "__main__":
    main()
