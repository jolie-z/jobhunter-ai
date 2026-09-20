#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""智联保存端点 no-op 探针：用官网现值原样回写 SelfEvaluate，验证鉴权/响应结构（不改数据）"""

import json
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
from browser_common import connect_page, get_platform_port

PORT = get_platform_port("zhilian")

JS = r"""
return (async function() {
    var captured = [];
    var origFetch = window.fetch;
    window.fetch = function(url, opts) {
        captured.push({kind: 'fetch', url: String(url).slice(0, 300), method: (opts && opts.method) || 'GET', body: opts && opts.body ? String(opts.body).slice(0, 1000) : null});
        return origFetch.apply(this, arguments);
    };
    var origOpen = XMLHttpRequest.prototype.open, origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(m, u) { this.__cap = {kind: 'xhr', method: m, url: String(u).slice(0, 300)}; return origOpen.apply(this, arguments); };
    XMLHttpRequest.prototype.send = function(b) { if (this.__cap) { this.__cap.body = b ? String(b).slice(0, 1000) : null; captured.push(this.__cap); } return origSend.apply(this, arguments); };

    var root = document.querySelector('#root');
    var store = root.__vue__.$store;
    var cr = store.state.resume.currentResume;
    var rl = store.state.resume.resumeList, ri = store.state.resume.resumeIndex;
    var se = (cr.SelfEvaluate || [])[0] || {};
    var out = {rid: rl[ri].resumeId, rno: rl[ri].resumeNumber.slice(0, 20), lang: store.state.resume.lang, sePath: se.path || null};
    try {
        var ok = await store.dispatch('resume/updateResumeAction', {
            resumeId: rl[ri].resumeId, resumeNumber: rl[ri].resumeNumber,
            nodeName: 'SelfEvaluate', lang: store.state.resume.lang,
            values: {selfEvaTitle: '自我介绍', selfEvaUserdefTitle: '自我介绍',
                     selfEvaContent: se.selfEvaContent || '', path: se.path || ''}
        });
        out.actionResult = ok;
    } catch(e) { out.actionErr = String(e).slice(0, 300); }
    await new Promise(function(r) { setTimeout(r, 1500); });
    window.fetch = origFetch;
    XMLHttpRequest.prototype.open = origOpen;
    XMLHttpRequest.prototype.send = origSend;
    out.captured = captured;
    return JSON.stringify(out);
})();
"""


def main():
    page = connect_page(PORT)
    tab = page.latest_tab
    raw = tab.run_js(JS, timeout=60)
    data = json.loads(raw)
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
