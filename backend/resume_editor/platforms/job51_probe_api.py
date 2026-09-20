#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
51job 回写前置探针（只读，不点击不写入）

目标：
1. 导航到简历中心，定位 PCResume 组件
2. 枚举组件全部 methods / $data.resumeInfo 键
3. 枚举 Vue 原型上的 $api.axiosInstances（baseURL/headers），确认在线简历保存走哪个实例
4. dump PCResume methods 源码片段里出现的 API 路径（正则提取 url 字符串）

运行：cd backend && .venv/bin/python resume_editor/platforms/job51_probe_api.py
"""

import json
import os
import sys
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
from browser_common import connect_page, get_platform_port

PORT = get_platform_port("51job")
RESUME_URL = "https://www.51job.com/resume/center"

JS_PROBE = r"""
return (function() {
    var out = {};
    var nuxt = document.querySelector('#__nuxt') || document.querySelector('#app');
    if (!nuxt || !nuxt.__vue__) return JSON.stringify({error: 'no vue root'});
    var vm = nuxt.__vue__;

    function findByName(c, n, d) {
        if (d > 10) return null;
        if ((c.$options.name || '') === n) return c;
        var ch = c.$children || [];
        for (var i = 0; i < ch.length; i++) { var f = findByName(ch[i], n, d+1); if (f) return f; }
        return null;
    }

    // 1. axiosInstances（$api 原型级）
    try {
        var inst = vm.$api && vm.$api.axiosInstances;
        if (inst) {
            out.axiosInstances = {};
            Object.keys(inst).forEach(function(k) {
                var ax = inst[k];
                out.axiosInstances[k] = {
                    baseURL: ax.defaults && ax.defaults.baseURL,
                    withCredentials: ax.defaults && ax.defaults.withCredentials,
                    headers: ax.defaults && ax.defaults.headers && ax.defaults.headers.common ? Object.keys(ax.defaults.headers.common) : []
                };
            });
        }
        out.apiKeys = vm.$api ? Object.keys(vm.$api) : [];
    } catch(e) { out.apiErr = String(e); }

    // 2. PCResume 组件
    var pc = findByName(vm, 'PCResume', 0);
    if (!pc) return JSON.stringify({error: 'PCResume not found', axiosInstances: out.axiosInstances});
    var methods = pc.$options.methods ? Object.keys(pc.$options.methods) : [];
    out.methods = methods;
    var ri = pc.$data && pc.$data.resumeInfo;
    out.resumeInfoKeys = ri ? Object.keys(ri) : [];
    out.dataKeys = pc.$data ? Object.keys(pc.$data) : [];

    // 3. methods 源码里提取 API 路径字符串
    var urls = {};
    methods.forEach(function(m) {
        try {
            var src = pc[m] && pc[m].toString ? pc[m].toString() : '';
            var re = /["'`]([\/][A-Za-z0-9_\-\/\.{}]+)["'`]/g, match;
            var found = [];
            while ((match = re.exec(src)) !== null) {
                if (match[1].length > 3 && match[1].indexOf('.vue') < 0) found.push(match[1]);
            }
            if (found.length) urls[m] = found;
        } catch(e) {}
    });
    out.methodUrls = urls;

    // 4. 组件自身是否持有 axios 实例（this.cupid / this.axios 等）
    out.instanceProps = [];
    ['cupid', 'axios', 'resumeApi', 'api'].forEach(function(k) {
        if (pc[k]) out.instanceProps.push(k);
    });

    return JSON.stringify(out);
})();
"""


def main():
    print("=" * 60)
    print("  51job 回写 API 探针（只读）")
    print("=" * 60)
    page = connect_page(PORT)
    print(f"  已连接浏览器 (端口 {PORT})")
    tab = page.latest_tab
    tab.get(RESUME_URL)
    time.sleep(8)
    if "login" in tab.url.lower() or "passport" in tab.url.lower():
        print("  [ERROR] 未登录")
        sys.exit(1)
    raw = tab.run_js(JS_PROBE)
    data = json.loads(raw)
    if data.get("error"):
        print(f"  [ERROR] {data['error']}")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    out_path = os.path.join(os.path.dirname(_SCRIPT_DIR), "data", "51job_probe_api.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n  已保存: {out_path}")


if __name__ == "__main__":
    main()
