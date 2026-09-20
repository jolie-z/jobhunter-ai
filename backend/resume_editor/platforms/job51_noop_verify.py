#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
51job 保存端点 no-op 验证（写回官网当前值 = 幂等，验证端点与 payload 结构）

对每个模块：GET 官网现值 → 原样 POST 回同一端点 → 校验 status=1。
全部幂等（值不变），用于标定回写报文。结果落盘 data/51job_noop_verify.json。

运行：cd backend && NO_PROXY=127.0.0.1,localhost .venv/bin/python resume_editor/platforms/job51_noop_verify.py
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
OUT_PATH = os.path.join(os.path.dirname(_SCRIPT_DIR), "data", "51job_noop_verify.json")

JS_NOOP = r"""
return (async function() {
  var out = {modules: {}};
  var nuxt = document.querySelector('#__nuxt') || document.querySelector('#app');
  if (!nuxt || !nuxt.__vue__) return JSON.stringify({error: 'no vue'});
  var vm = nuxt.__vue__;
  function findByName(c, n, d) {
    if (d > 10) return null;
    if ((c.$options.name || '') === n) return c;
    var ch = c.$children || [];
    for (var i = 0; i < ch.length; i++) { var f = findByName(ch[i], n, d + 1); if (f) return f; }
    return null;
  }
  var pc = findByName(vm, 'PCResume', 0);
  if (!pc) return JSON.stringify({error: 'PCResume not found'});
  var rid = String(pc.$data.resumeInfo.resumeId);
  var ra = vm.$api.resumeApi;
  out.resumeId = rid;

  function norm(r) { return (r && r.resultbody !== undefined) ? r : (r && r.data); }
  async function call(name, fn, args) {
    try {
      var r = norm(await fn.apply(null, args));
      var ok = String(r && r.status) === '1';
      out.modules[name] = {ok: ok, status: r && r.status, message: r && r.message,
                           body: JSON.stringify(r).slice(0, 900)};
    } catch (e) {
      out.modules[name] = {ok: false, error: String(e).slice(0, 400)};
    }
  }

  // ---------- 1. 自我介绍 ----------
  var si = norm(await ra.getSelfIntroduction(rid, {api_key: '51job'}));
  out.selfIntro_current_len = si.resultbody && String(si.resultbody.selfIntroduction || '').length;
  await call('self_introduction', ra.editSelfIntroduction,
             [rid, {selfIntroduction: si.resultbody.selfIntroduction, api_key: '51job'}]);

  // ---------- 2. 工作经历（首条原样回写） ----------
  var works = (pc.$data.resumeInfo.works || []);
  if (works.length) {
    var w = JSON.parse(JSON.stringify(works[0]));
    out.work_payload_keys = Object.keys(w);
    await call('works_edit', ra.editWorkExp, [rid, w.id, w]);
  } else { out.modules.works_edit = {ok: false, error: '官网无工作经历条目'}; }

  // ---------- 3. 项目经历（首条原样回写） ----------
  var projs = (pc.$data.resumeInfo.projects || []);
  if (projs.length) {
    var pj = JSON.parse(JSON.stringify(projs[0]));
    out.project_payload_keys = Object.keys(pj);
    await call('projects_edit', ra.getProjectEdit, [rid, pj.id, pj]);
  } else { out.modules.projects_edit = {ok: false, error: '官网无项目条目'}; }

  // ---------- 4. 教育经历（首条原样回写） ----------
  var edus = (pc.$data.resumeInfo.educations || []);
  if (edus.length) {
    var ed = JSON.parse(JSON.stringify(edus[0]));
    out.edu_payload_keys = Object.keys(ed);
    await call('educations_edit', ra.editEducation, [rid, ed.id, ed]);
  } else { out.modules.educations_edit = {ok: false, error: '官网无教育条目'}; }

  // ---------- 5. 求职意向（首条原样回写） ----------
  var ints = (pc.$data.resumeInfo.intentions || []);
  if (ints.length) {
    var it = JSON.parse(JSON.stringify(ints[0]));
    out.intention_payload_keys = Object.keys(it);
    await call('intentions_edit', ra.editIntention, [it.id, it]);
  } else { out.modules.intentions_edit = {ok: false, error: '官网无求职意向'}; }

  // ---------- 6. 专业技能（首条原样回写） ----------
  var sks = (pc.$data.resumeInfo.skills || []);
  if (sks.length) {
    var sk = JSON.parse(JSON.stringify(sks[0]));
    await call('skills_edit', ra.getSkillItEdit, [rid, sk.id, sk]);
  } else { out.modules.skills_edit = {ok: false, error: '官网无技能条目'}; }

  // ---------- 7. 语言能力（首条原样回写） ----------
  var langs = (pc.$data.resumeInfo.language || []);
  if (langs.length) {
    var lg = JSON.parse(JSON.stringify(langs[0]));
    await call('language_edit', ra.languageEdit, [rid, lg.id, lg]);
  } else { out.modules.language_edit = {ok: false, error: '官网无语言条目'}; }

  // ---------- 8. 资格证书（multi-edit 原样回写） ----------
  var certs = (pc.$data.resumeInfo.certifications || []);
  if (certs.length) {
    var cs = JSON.parse(JSON.stringify(certs));
    out.cert_count = cs.length;
    await call('certifications_multi_edit', ra.multiEditCertification,
               [rid, {certifications: cs, api_key: '51job'}]);
  } else { out.modules.certifications_multi_edit = {ok: false, error: '官网无证书条目'}; }

  // ---------- 9. 基本信息（原样回写，editBaseInfo） ----------
  var bi = norm(await ra.getBaseInfo(rid, {api_key: '51job'}));
  if (bi.resultbody) {
    var bio = JSON.parse(JSON.stringify(bi.resultbody));
    out.baseinfo_payload_keys = Object.keys(bio);
    await call('baseinfo_edit', ra.editBaseInfo, [bio, rid]);
  } else { out.modules.baseinfo_edit = {ok: false, error: 'getBaseInfo 失败'}; }

  return JSON.stringify(out);
})();
"""


def main():
    print("=" * 60)
    print("  51job 保存端点 no-op 验证（幂等）")
    print("=" * 60)
    page = connect_page(PORT)
    print(f"  已连接浏览器 (端口 {PORT})")
    tab = page.latest_tab
    tab.get(RESUME_URL)
    time.sleep(8)
    if "login" in tab.url.lower() or "passport" in tab.url.lower():
        print("  [ERROR] 未登录")
        sys.exit(1)

    # 等待 resumeInfo 加载
    for _ in range(10):
        ready = tab.run_js("""
        return (function(){
            var n = document.querySelector('#__nuxt');
            if (!n || !n.__vue__) return 'no';
            function f(c,n,d){ if(d>10)return null; if((c.$options.name||'')===n)return c;
              var ch=c.$children||[]; for(var i=0;i<ch.length;i++){var x=f(ch[i],n,d+1); if(x)return x;} return null; }
            var pc = f(n.__vue__,'PCResume',0);
            return (pc && pc.$data.resumeInfo && pc.$data.resumeInfo.resumeId) ? 'yes' : 'no';
        })();
        """)
        if ready == "yes":
            break
        time.sleep(1)

    raw = tab.run_js(JS_NOOP)
    data = json.loads(raw)
    if data.get("error"):
        print(f"  [ERROR] {data['error']}")
        sys.exit(1)

    print(f"  resumeId = {data.get('resumeId')}\n")
    ok_cnt = 0
    for name, r in data.get("modules", {}).items():
        flag = "OK " if r.get("ok") else "FAIL"
        if r.get("ok"):
            ok_cnt += 1
        detail = r.get("message") or r.get("error") or ""
        print(f"  [{name}] {flag} status={r.get('status')} {detail}")
        if not r.get("ok"):
            print(f"      body: {(r.get('body') or '')[:300]}")
    print(f"\n  总计: {ok_cnt}/{len(data.get('modules', {}))} 端点 no-op 通过")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  详细结果: {OUT_PATH}")


if __name__ == "__main__":
    main()
