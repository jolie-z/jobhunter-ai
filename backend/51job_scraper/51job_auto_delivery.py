#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
前程无忧 (51job) 全自动精准投递引擎（确定性版 v2）

核心策略（2026-07-23 实测验证，2026-08-14 修正）：
  51job 的 light-apply-job 默认只发「在线简历」（请求不带 resumeId 时）。
  投递成功后响应里的 popupAttachResumeList 是前端「是否补充附件简历」弹窗的
  数据源，必须再调 modify-attach-resume（携带 cvLogIdList + attachResumeId，
  modifyType="add"，attachmentScene="3"）才能把附件挂到本次投递上——
  这正是 UI 弹窗点「确认」时发的同一个请求。旧版引擎只清场不处理弹窗，
  导致雇主永远只收到在线简历（2026-08-14 用户反馈的问题根因）。
  清场策略作为辅助保留：减少弹窗里的干扰项，避免误挂错附件。

关键实现：
  - 附件列表/删除接口统一走页面 Vue 原型上的 $api.axiosInstances.cupid
    (baseURL=cupid.51job.com, withCredentials=false, 响应拦截器已 unwrap → 返回值即 body, status 为字符串"1")。
  - cvLogId 通过 monkey-patch 组件 cupid.post 截获 light-apply-job 的已解析响应。
  - 附件简历上限 3 份：需新上传且已满时，自动删最旧的一份腾名额，再走正常上传流程。

投递链路：
  1. 连接已登录 Edge (端口 9227)，打开岗位详情页
  2. 用 cupid 读附件列表，定位目标附件(按 pdf_name 精确匹配)
     - 不存在/未过审 → 下载飞书 PDF → 上传(满3份自动删最旧) → 轮询直到过审(status="01")
  3. ★ 删除所有其他附件，只留目标（确保投递时唯一）
  4. monkey-patch cupid.post 截获 light-apply-job 响应 + popupAttachResumeList
  5. 点「立即投递」触发 light-apply-job，拿到 cvLogId
  6. ★ 用 cvLogIdList + 目标 attachResumeId 调 modify-attach-resume 挂接附件
  7. 成功则回写飞书：跟进状态=已投递，投递日期=今天
"""

import os
import sys
import time
import json
from datetime import date
from urllib.parse import urlparse

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app.services.feishu_service import update_feishu_record
from app.core.feishu_utils import download_feishu_file
from app.automation import upload_quota
from playwright.sync_api import sync_playwright

# 纯标准库零包连锁，任何 sys.path 含 backend 根的环境都可导入
from engine_guard import EngineGuardError, verify_browser_identity

try:
    from app.session.registry import PLATFORM_CONFIGS, get_platform_port, get_profile_path
    BROWSER_DEBUG_PORT = get_platform_port("51job")
    DEFAULT_PROFILE_DIR = get_profile_path("51job")
    # 登录页域名单一真理源在 session/registry（登录态预检同款）
    LOGIN_PAGE_DOMAINS = tuple(PLATFORM_CONFIGS["51job"].login_page_indicators)
except Exception:
    BROWSER_DEBUG_PORT = 9227
    DEFAULT_PROFILE_DIR = os.path.join(_PROJECT_ROOT, "backend", "data", "profiles", "51job")
    LOGIN_PAGE_DOMAINS = ("login.51job.com", "passport.51job.com")

# ==========================================
# 全局常量
# ==========================================
RESUME_MANAGE_URL = "https://www.51job.com/resume/center?lang=c"
TEMP_DIR = os.path.join(_PROJECT_ROOT, "temp_resumes")
ATTACH_LIMIT = 3            # 51job 附件简历上限
REVIEW_POLL_TIMES = 5       # 等待附件过审的轮询次数
REVIEW_POLL_INTERVAL = 8    # 每次轮询间隔(秒)
MASS_RESUME_NAME = "我的简历"  # 51job 海投模式固定附件名（依用户要求统一为「我的简历」）
# 海投会话：51job 附件上传按日限次（720721），海投「我的简历」每天只传一次，
# 当日后续海投岗位一律复用（新鲜度由 upload_quota.mass_resume_date 持久化判定，跨进程/跨批次有效）。
# executor 在新批量任务开始时调 reset_mass_apply_session() 置位 _MASS_FORCE_UPLOAD，
# 让下一海投岗强制重传最新母本。
_MASS_FORCE_UPLOAD = False


def reset_mass_apply_session():
    """新批量任务开始时重置海投会话状态，使本任务首个海投岗位强制重新上传海投简历。"""
    global _MASS_FORCE_UPLOAD
    _MASS_FORCE_UPLOAD = True

# ==========================================
# 页面内 JS：附件列表 / patch / 投递
# ==========================================

# 在任意 51job 页面用 $api.axiosInstances.cupid GET 附件列表
JS_GET_ATTACH_LIST = r"""
async () => {
  function findVue(el){ if(!el) return null; if(el.__vue__) return el.__vue__; for(const c of el.children||[]){const v=findVue(c); if(v) return v;} return null; }
  const vm = findVue(document.querySelector("#app") || document.body);
  if(!vm) return {ok:false, err:"no vue"};
  const cupid = vm.$api && vm.$api.axiosInstances && vm.$api.axiosInstances.cupid;
  if(!cupid) return {ok:false, err:"no $api.axiosInstances.cupid"};
  try {
    const r = await cupid.get("/open/attachment-resume/center", { params: { api_key: "51job" } });
    const body = (r && r.resultbody !== undefined) ? r : (r && r.data);
    const list = (body && body.resultbody && body.resultbody.attachmentResumeList) || [];
    return { ok:true, list: list.map(it => ({ id: String(it.id), name: it.name, status: it.status, defaultPost: it.defaultPost, createTime: it.createTime || "" })) };
  } catch(e) { return { ok:false, err: String(e).slice(0,200) }; }
}
"""

# 找到 PCApplyJob 组件，monkey-patch 其 cupid.post 截获 light-apply-job 响应
JS_SETUP_PATCH = r"""
() => {
  function findVue(el){ if(!el) return null; if(el.__vue__) return el.__vue__; for(const c of el.children||[]){const v=findVue(c); if(v) return v;} return null; }
  const vm = findVue(document.querySelector("#app") || document.body);
  if(!vm) return {ok:false, err:"no vue"};
  let pc = null;
  const stack=[vm]; const seen=new Set();
  while(stack.length){ const c=stack.pop(); if(!c||seen.has(c))continue; seen.add(c);
    if(c.$options && c.$options.methods && c.$options.methods.applyJobFun && c.cupid){ pc=c; break; }
    for(const ch of (c.$children||[])) stack.push(ch);
    if(c.$refs){ for(const rk of Object.keys(c.$refs)){ const rv=c.$refs[rk]; if(rv&&rv.$options)stack.push(rv); else if(Array.isArray(rv))rv.forEach(x=>x&&x.$options&&stack.push(x)); } }
  }
  if(!pc) return {ok:false, err:"no PCApplyJob with cupid"};
  const cupid = pc.cupid;
  window.__cupid = cupid;
  if(!cupid.__patched){
    const orig = cupid.post.bind(cupid);
    cupid.post = async function(...args){
      const url = args[0];
      const res = await orig(...args);
      try {
        if(typeof url === "string" && url.indexOf("light-apply-job") > -1){
          const body = (res && res.resultbody !== undefined) ? res : (res && res.data);
          window.__applyResp = body;
          const lst = body && body.resultbody && body.resultbody.applyJobResult && body.resultbody.applyJobResult.applySuccessJobList;
          window.__cvLogIds = lst ? lst.map(x => x.cvLogId).filter(Boolean) : [];
          // 2026-08-14：捕获「补充附件简历」弹窗数据源，投递后需用它挂接附件
          window.__popupAttach = (body && body.resultbody && body.resultbody.popupAttachResumeList) || null;
        }
      } catch(e){ window.__patchErr = String(e); }
      return res;
    };
    cupid.__patched = true;
  }
  return {ok:true};
}
"""

JS_GET_APPLY_RESULT = r"""
() => ({ resp: window.__applyResp || null, cvLogIds: window.__cvLogIds || [], popup: window.__popupAttach || null, patchErr: window.__patchErr || null })
"""

# 2026-09-16：在任何上传之前只读 ApplyjobBtn.detailData.isApply，识别「此前已投过」的岗位。
# 旧流程到 Step 5 才发现 isApply，此前已白烧一次附件上传配额（51job 按日限次）。
JS_CHECK_APPLIED = r"""
() => { /* CHECK_APPLIED */
  function findVue(el){ if(!el) return null; if(el.__vue__) return el.__vue__; for(const c of el.children||[]){const v=findVue(c); if(v) return v;} return null; }
  const vm = findVue(document.querySelector("#app") || document.body);
  if(!vm) return {ok:false, err:"no vue"};
  const stack=[vm]; const seen=new Set(); let btn=null;
  while(stack.length){ const c=stack.pop(); if(!c||seen.has(c))continue; seen.add(c);
    const ms=(c.$options||{}).methods||{};
    if(ms.goApply && ms.buildJobItem){ btn=c; break; }
    for(const ch of (c.$children||[])) stack.push(ch);
    if(c.$refs){ for(const rk of Object.keys(c.$refs)){ const rv=c.$refs[rk]; if(rv&&rv.$options)stack.push(rv); else if(Array.isArray(rv))rv.forEach(x=>x&&x.$options&&stack.push(x)); } }
  }
  if(!btn || !btn.detailData) return {ok:false, err:"no ApplyjobBtn/detailData"};
  return {ok:true, isApply: !!btn.detailData.isApply, jobId: String(btn.detailData.jobId || "")};
}
"""

# 2026-08-14：投递成功后把附件简历挂接到本次投递（等价于 UI 弹窗点「确认」，
# 参数结构与 selectAttachmentResume.onConfirm 完全一致）。自包含：现场重新
# 定位 PCApplyJob 组件拿 cupid，不依赖 window.__cupid（上下文销毁重载后仍可用）
JS_ATTACH_RESUME = r"""
async ({cvLogIdList, attachResumeId}) => {
  function findVue(el){ if(!el) return null; if(el.__vue__) return el.__vue__; for(const c of el.children||[]){const v=findVue(c); if(v) return v;} return null; }
  let cupid = window.__cupid;
  for (let t = 0; t < 10; t++) {
    if (cupid) break;
    const vm = findVue(document.querySelector("#app") || document.body);
    if(vm){
      if(vm.$api && vm.$api.axiosInstances && vm.$api.axiosInstances.cupid){
        cupid = vm.$api.axiosInstances.cupid;
        break;
      } else {
        const stack=[vm]; const seen=new Set(); let pc=null;
        while(stack.length){ const c=stack.pop(); if(!c||seen.has(c))continue; seen.add(c);
          if(c.$options && c.$options.methods && c.$options.methods.applyJobFun && c.cupid){ pc=c; break; }
          if(c.$api && c.$api.axiosInstances && c.$api.axiosInstances.cupid){ cupid = c.$api.axiosInstances.cupid; break; }
          for(const ch of (c.$children||[])) stack.push(ch);
          if(c.$refs){ for(const rk of Object.keys(c.$refs)){ const rv=c.$refs[rk]; if(rv&&rv.$options)stack.push(rv); else if(Array.isArray(rv))rv.forEach(x=>x&&x.$options&&stack.push(x)); } }
        }
        if(pc) cupid = pc.cupid;
        if(cupid) break;
      }
    }
    await new Promise(r => setTimeout(r, 500));
  }
  if(!cupid) return {ok:false, err:"no cupid after polling"};
  try {
    const r = await cupid.post("/open/user-apply/open/user-apply/modify-attach-resume", {
      cvLogIdList: cvLogIdList,
      attachResumeId: attachResumeId,
      setDefaultFlag: true,
      modifyType: "add",
      attachmentScene: "3"
    });
    return {ok:true, status: r && r.status, message: (r && r.message) || "", hasResultbody: !!(r && r.resultbody)};
  } catch(e) { return {ok:false, err: String(e).slice(0,200)}; }
}
"""

# 2026-08-14 终极方案：JS 层直接调 ApplyjobBtn.$refs.pcApply.applyJobFun 发投递。
# 背景：点按钮路径下前端拿到响应前就触发同源重载，XHR 被 abort，
# 服务端已受理但响应永远截获不到（名幸/玛速玛/如春/安居宝四岗实测全丢 cvLogId）。
# 直接调用不触发重载；响应不依赖 applyJobFun 返回值（其内部 UI 处理可能报错且
# 无返回值），改从 Step 4 已 patch 的 cupid.post 写入的 window.__applyResp 读取。
JS_DIRECT_APPLY = r"""
async function directApply() {
  function findVue(el){ if(!el) return null; if(el.__vue__) return el.__vue__; for(const c of el.children||[]){const v=findVue(c); if(v) return v;} return null; }
  const vm = findVue(document.querySelector("#app") || document.body);
  if(!vm) return {ok:false, err:"no vue"};
  const stack=[vm]; const seen=new Set(); let btn=null;
  while(stack.length){ const c=stack.pop(); if(!c||seen.has(c))continue; seen.add(c);
    const ms=(c.$options||{}).methods||{};
    if(ms.goApply && ms.buildJobItem){ btn=c; break; }
    for(const ch of (c.$children||[])) stack.push(ch);
    if(c.$refs){ for(const rk of Object.keys(c.$refs)){ const rv=c.$refs[rk]; if(rv&&rv.$options)stack.push(rv); else if(Array.isArray(rv))rv.forEach(x=>x&&x.$options&&stack.push(x)); } }
  }
  if(!btn) return {ok:false, err:"no ApplyjobBtn"};
  if(!btn.detailData || !btn.detailData.jobId) return {ok:false, err:"no detailData"};
  if(btn.detailData.isApply) return {ok:false, err:"already applied", isApply:true};
  const pc = btn.$refs.pcApply;
  if(!pc || !pc.applyJobFun) return {ok:false, err:"no pcApply ref"};
  if(!window.__cupid || !window.__cupid.__patched) return {ok:false, err:"cupid not patched (Step 4 未生效)"};
  // 清旧值，避免读到历史响应
  window.__applyResp = null; window.__cvLogIds = []; window.__popupAttach = null;
  try {
    await pc.applyJobFun({applyType:"single", applyJobList:[btn.buildJobItem(btn.detailData)], fromModule:"详情单投"});
  } catch(e) {
    // applyJobFun 内部 UI 处理可能报错（不影响投递本身，响应已由 patch 截获）
  }
  const body = window.__applyResp;
  if(!body) return {ok:false, err:"投递已触发但未截获到 light-apply-job 响应"};
  return {ok:true, status: body.status, message: body.message || "",
          cvLogIds: window.__cvLogIds || [],
          popup: window.__popupAttach || null,
          raw: (JSON.stringify(body) || "").slice(0, 500)};
}
"""

JS_DELETE_ATTACH = r"""
async (attachId) => {
  function findVue(el){ if(!el) return null; if(el.__vue__) return el.__vue__; for(const c of el.children||[]){const v=findVue(c); if(v) return v;} return null; }
  const vm = findVue(document.querySelector("#app") || document.body);
  if(!vm) return {ok:false, err:'no vue'};
  try {
    const uploadResumeId = String(attachId);
    const resumeApi = vm.$api && vm.$api.resumeApi;
    let rawRes = null;

    if (resumeApi && typeof resumeApi.attachmentResumeRemove === 'function') {
      rawRes = await resumeApi.attachmentResumeRemove({ uploadResumeId }, { loading: false });
    } else {
      const cupid = vm.$api && vm.$api.axiosInstances && vm.$api.axiosInstances.cupid;
      if (!cupid || typeof cupid.get !== 'function') return {ok:false, err:'no api'};
      // 官方真实接口为 GET /open/attachment-resume/remove，带入时间戳防代理/浏览器缓存
      rawRes = await cupid.get("/open/attachment-resume/remove", {
        params: { uploadResumeId, api_key: "51job", _t: Date.now() }
      });
    }

    // 规范化解包：Axios 响应取 rawRes.data，若为官方拦截器解包后的业务响应对象则直接使用 rawRes
    const payload = (rawRes && rawRes.data && typeof rawRes.data === 'object') ? rawRes.data : rawRes;
    const bizStatus = (payload && payload.status !== undefined) ? payload.status : null;
    const bizMsg = (payload && (payload.message || payload.msg)) || "";
    return { ok: String(bizStatus) === "1", status: bizStatus, msg: String(bizMsg) };
  } catch(e) {
    return {ok:false, err: String(e).slice(0,200)};
  }
}
"""

# 2026-08-14 patch cupid.post 截获 attachment-resume/add 业务响应。
# 根因背景：add 响应慢（当前网络环境实测 25~30s，曾被误判为「请求挂起」），
# 且业务失败不抛错——今日上传次数达上限时返回 {status:"720721"}，
# 前端仅弹一条 toast，旧代码等 8s 就认定上传成功 → 附件永远不在列表 →
# popupAttachResumeList 为空 → 投递只发在线简历。必须在确认添加前 patch。
JS_PATCH_ADD = r"""
() => {
  function findVue(el){ if(!el) return null; if(el.__vue__) return el.__vue__; for(const c of el.children||[]){const v=findVue(c); if(v) return v;} return null; }
  const vm = findVue(document.querySelector("#app") || document.body);
  if(!vm) return {ok:false, err:"no vue"};
  const cupid = vm.$api && vm.$api.axiosInstances && vm.$api.axiosInstances.cupid;
  if(!cupid) return {ok:false, err:"no cupid"};
  window.__addResp = null;
  if(!cupid.__patchedAdd){
    const orig = cupid.post.bind(cupid);
    cupid.post = async function(...args){
      const url = args[0];
      let res, threw = null;
      try { res = await orig(...args); } catch(e) { threw = String(e).slice(0,200); }
      try {
        if(typeof url === "string" && url.indexOf("attachment-resume/add") > -1){
          window.__addResp = {
            threw: threw,
            status: res ? res.status : undefined,
            message: res ? res.message : undefined,
            hasResultbody: !!(res && res.resultbody !== undefined)
          };
        }
      } catch(e) { window.__addResp = {patchErr: String(e)}; }
      if(threw) throw new Error(threw);
      return res;
    };
    cupid.__patchedAdd = true;
  }
  return {ok:true};
}
"""


# ==========================================
# 基础辅助
# ==========================================

def _connect_browser(p):
    """连接到已登录的 Edge 浏览器，复用登录态；若 CDP 未就绪则自动拉起持久化 Profile 实例"""
    # 🛡️ 环境守卫（Q24）：端口占用者身份校验。守卫拒绝时直接抛出——
    # 绝不能落入下方 launch 兜底（陌生占用者还在 9227 上，自起会撞端口或误附）
    ok, guard_reason = verify_browser_identity(BROWSER_DEBUG_PORT, DEFAULT_PROFILE_DIR, platform="51job")
    if not ok:
        raise EngineGuardError(f"51job 引擎环境守卫拒绝连接浏览器：{guard_reason}")
    print(f"   🔗 正在连接 Edge 浏览器 (端口 {BROWSER_DEBUG_PORT})...")
    try:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{BROWSER_DEBUG_PORT}", timeout=15000)
        print(f"   ✅ CDP 连接建立成功")
        
        existing_contexts = browser.contexts
        if existing_contexts:
            ctx = existing_contexts[0]
            try:
                if ctx.pages:
                    return browser, ctx
            except Exception:
                pass
            # 默认 context 无页面时在原 context 上开新标签页。
            # ⚠️ 不能 browser.new_context()：CDP 下那是隔离上下文，不继承 Profile 登录态。
            return browser, ctx

        ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
        )
        return browser, ctx

    except Exception as e:
        print(f"   ⚠️ CDP 连接未就绪 ({e})，正在自动拉起 Edge 持久化 Profile 实例...")
        edge_path = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
        profile_dir = DEFAULT_PROFILE_DIR
        os.makedirs(profile_dir, exist_ok=True)

        ctx = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            executable_path=edge_path if os.path.exists(edge_path) else None,
            headless=False,
            viewport={"width": 1920, "height": 1080},
            args=[
                "--no-first-run",
                "--no-default-browser-check",
                # ⚠️ 必须注册到 9227 调试端口，否则后续 collector / 预检 attach 不上这个实例
                f"--remote-debugging-port={BROWSER_DEBUG_PORT}",
            ]
        )
        print(f"   ✅ Edge 持久化实例启动成功")
        return None, ctx


def _close_popups(page):
    """关闭可能的干扰弹窗"""
    for sel in [".close-btn", "text=我知道了", "text=关闭"]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=800):
                btn.click()
                time.sleep(0.5)
        except Exception:
            continue


def _safe_reload(page, timeout: int = 45000) -> bool:
    """容错刷新：51job 页面常驻长轮询，networkidle 永远等不到（2026-09-16 真机 45s 超时中断整岗）。
    改等 domcontentloaded，超时只告警不抛出，交给调用方的固定 sleep 兜底。"""
    try:
        page.reload(wait_until="domcontentloaded", timeout=timeout)
        return True
    except Exception as e:
        print(f"   ⚠️ 页面刷新超时/异常（继续流程）: {str(e)[:80]}")
        return False


def _safe_goto(page, url: str, timeout: int = 45000) -> bool:
    """容错导航：同 _safe_reload，导航超时不中断投递。"""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        return True
    except Exception as e:
        print(f"   ⚠️ 页面导航超时/异常（继续流程）: {str(e)[:80]}")
        return False


def _is_today(create_time) -> bool:
    """51job 附件 createTime 形如 'YYYY-MM-DD'（2026-09-16 真机实测），取前 10 位比对本地日期。"""
    return str(create_time or "")[:10] == date.today().isoformat()


def _dump_upload_diagnostics(page):
    """上传按钮找不到时输出页面诊断（URL/标题/关键元素计数/截图），协助判断是
    登录态失效、账号未创建在线简历（侧栏显示「请先创建简历」）还是页面结构再变更。"""
    try:
        print(f"   🔍 [诊断] 当前URL: {page.url}")
        print(f"   🔍 [诊断] 页面标题: {page.title()}")
        for sel in ["div.upload_btn", "div.uploadFile", "text=上传附件简历", "text=请先创建简历",
                    "text=登录", "div.myFile.resume", "div.priorityCreate"]:
            try:
                n = page.locator(sel).count()
                vis = False
                if n:
                    try:
                        vis = page.locator(sel).first.is_visible(timeout=800)
                    except Exception:
                        pass
                print(f"   🔍 [诊断] {sel}: count={n} visible={vis}")
            except Exception:
                continue
        import os
        shot = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "temp_resumes", "51job_upload_debug.png")
        os.makedirs(os.path.dirname(shot), exist_ok=True)
        page.screenshot(path=shot, full_page=False)
        print(f"   🔍 [诊断] 截图已保存: {os.path.abspath(shot)}")
    except Exception as e:
        print(f"   🔍 [诊断] 快照失败: {e}")


def _get_attach_list(page, retries: int = 4, wait: float = 3.0):
    """在当前 51job 页面用 cupid axios 拿附件列表。失败返回 []。

    2026-08-14：页面刚导航完成时 Vue 可能尚未挂载（err="no vue"/"no cupid"），
    带重试轮询等待 Vue 就绪，避免上传/挂接流程因时序问题误判无附件。
    """
    res = {"ok": False, "err": "not called"}
    for attempt in range(1, retries + 1):
        try:
            res = page.evaluate(JS_GET_ATTACH_LIST)
        except Exception as e:
            print(f"   ⚠️ 取附件列表异常: {e}")
            res = {"ok": False, "err": str(e)[:100]}
        if res.get("ok"):
            return res.get("list", []) or []
        if attempt < retries:
            print(f"   ⏳ 取附件列表失败({res.get('err')})，Vue 可能未挂载，{wait}s 后重试 ({attempt}/{retries})...")
            time.sleep(wait)
    print(f"   ⚠️ 取附件列表最终失败: {res.get('err')}")
    return []


def _extract_job_info_from_page(page):
    """从岗位详情页提取 (公司名, 岗位名)。优先解析 title，回退 DOM。"""
    title_text = page.title()
    if "前程无忧" in title_text:
        parts = [p.strip() for p in title_text.split("|")]
        if len(parts) >= 4:
            jt = parts[0].replace("招聘", "").strip()
            cn = parts[3].strip()
            if jt and cn:
                return cn, jt
    jt = None
    for sel in [".cn h1", "h1[title]", ".jname", "h1.name"]:
        try:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible(timeout=1000):
                raw = el.inner_text().strip()
                if raw:
                    jt = raw
                    break
        except Exception:
            continue
    cn = None
    for sel in [".cname a", ".com_name a", "a.catn", ".cName"]:
        try:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible(timeout=1000):
                raw = el.inner_text().strip()
                if raw:
                    cn = raw
                    break
        except Exception:
            continue
    return cn, jt


def _attachment_name_matches_job(att_name: str, page_company: str, page_title: str) -> bool:
    """附件名格式 {公司}_{岗位}：公司互相包含、岗位前5字相同视为匹配。"""
    if not att_name or not page_company or not page_title:
        return False
    parts = att_name.split("_", 1)
    if len(parts) != 2:
        return False
    att_company, att_title = parts[0].strip(), parts[1].strip()
    pg_company, pg_title = page_company.strip(), page_title.strip()
    if att_company not in pg_company and pg_company not in att_company:
        return False
    cmp_len = min(5, len(att_title), len(pg_title))
    if cmp_len == 0:
        return False
    return att_title[:cmp_len] == pg_title[:cmp_len]


def _name_matches(actual: str, expected: str) -> bool:
    """51job 附件名有长度限制(约20字)，重命名可能被截断。
    用双向前缀匹配：actual 以 expected 开头，或 expected 以 actual 开头。"""
    if not actual or not expected:
        return False
    if actual == expected:
        return True
    # 双向 startswith（处理截断）
    return actual.startswith(expected) or expected.startswith(actual)


# 与 app/session/registry.py PLATFORM_CONFIGS["51job"].login_page_indicators 同源（见文件头部导入）
LOGIN_LOST_ERROR = "[登录] 51job 登录态失效（已跳转登录页），请在 9227 端口 Edge 重新登录后重试"
SLIDER_VERIFY_ERROR = "[登录] 51job 触发滑动验证（登录态失效或风控），请在 9227 端口 Edge 手动完成验证并登录后重试"
# 槽位满且全为今日附件（删除会破坏今日投递记录的附件绑定）→ [简历] 持久性标记，转人工清理
SLOTS_FULL_TODAY_ERROR = "[简历] 51job附件槽位已满且全部为今日上传，删除会破坏今日已投岗位的附件绑定，请手动清理附件后重试"
SLOT_FREE_FAILED_ERROR = "[简历] 51job附件槽位已满且删除非今日旧附件失败，请手动清理附件或检查网络后重试"
# 岗位页无投递组件且缺少岗位信息（标题仅「招聘 | 前程无忧」）→ 岗位已下架/链接失效，上传前止损
JOB_PAGE_INVALID_ERROR = "[下架] 51job 岗位页无投递组件且无岗位信息（可能已下架或链接失效），已跳过附件上传"
# _upload_resume_to_51job 因结构化原因放弃时写入，deliver_job 读取后回写飞书失败日志（每次上传前清空）
_LAST_UPLOAD_BLOCK = ""


def _detect_login_block(page) -> str:
    """登录态失效 / 触发滑动验证时返回结构化 [登录] 文案，否则返回空串。
    滑块验证只识别不绕过：必须由用户在 9227 端口的真实 Edge 手动完成。
    [登录] 命中 failure_triage.TRANSIENT_PATTERNS，波次会在用户重新登录后自动重试。"""
    try:
        url = page.url or ""
        title = page.title() or ""
    except Exception:
        return ""
    if any(domain in url for domain in LOGIN_PAGE_DOMAINS):
        return LOGIN_LOST_ERROR
    if "滑动验证" in title:
        return SLIDER_VERIFY_ERROR
    return ""


def _check_already_applied(page, tries: int = 3, wait: float = 2.0) -> tuple:
    """岗位页只读探测投递组件：返回 (组件是否存在, detailData.isApply 是否已投)。
    组件存在且已投 → 幂等成功不上传；组件不存在 → 由调用方结合页面岗位信息判断是否已下架。
    探测异常按「组件不存在」返回，绝不在此处触发投递。"""
    for attempt in range(1, tries + 1):
        try:
            res = page.evaluate(JS_CHECK_APPLIED)
        except Exception as e:
            res = {"ok": False, "err": str(e)[:80]}
        if res.get("ok"):
            return True, bool(res.get("isApply"))
        if attempt < tries:
            time.sleep(wait)
    return False, False


OFFLINE_PAGE_TEXTS = ("当前职位审核中或已下线", "职位已下线", "该职位已下线")


def _page_says_offline(page) -> bool:
    """岗位页正文是否明示已下线（agy 真机复核：下架页正文为「当前职位审核中或已下线」）。"""
    try:
        for text in OFFLINE_PAGE_TEXTS:
            if page.locator(f"text={text}").count() > 0:
                return True
    except Exception:
        pass
    return False


def _pick_target_attachment(attach_list, pdf_name: str, allow_unreviewed_today: bool = False):
    """上传之后按名选目标附件——**只在今日上传的附件里选**：今日已过审优先，海投允许回退到
    「今日上传但仍审核中」。非今日的同名历史附件一律不选（即便已过审），否则会截胡今日刚传的新版、
    投出陈旧母本（同名旧附件本应已在上传前清理，此处是 API 删除失败时的最后防线）。
    2026-09-16 真机：海投刚传的附件未过审 → target_id 为空 → Step 6 无 ID 可挂 → 雇主只收到在线简历。"""
    todays = [it for it in attach_list
              if _name_matches(str(it.get("name", "")), pdf_name) and _is_today(it.get("createTime"))]
    reviewed = next((it for it in todays if str(it.get("status")) == "01"), None)
    if reviewed is not None or not allow_unreviewed_today:
        return reviewed
    return todays[0] if todays else None


def _mark_delivered_in_feishu(record_id: str, note: str = "") -> None:
    """幂等成功（岗位此前已投过）时同步飞书：跟进状态=已投递、投递日期=今天、清空失败日志。"""
    if not record_id:
        return
    try:
        update_feishu_record(record_id, {
            "跟进状态": "已投递",
            "投递日期": int(time.time() * 1000),
            "自动投递失败日志": "",
        })
        print(f"      ✅ 飞书状态已同步（已投递）{note}")
    except Exception as e:
        print(f"      ⚠️ 飞书同步失败: {e}")


# ==========================================
# 附件简历管理（上传 / 腾位 / 重命名 / 等过审）
# ==========================================

def _rename_latest_attachment(page, new_name: str) -> bool:
    """重命名最后一个附件简历（即刚上传的那个）。失败不阻塞投递。"""
    files = page.locator("div.myFile.resume")
    if files.count() == 0:
        return False
    last = files.nth(files.count() - 1)
    more = last.locator(".moreIcon")
    if more.count() == 0 or not more.first.is_visible(timeout=3000):
        print("   ⚠️ 未找到三点菜单，跳过重命名")
        return False
    more.first.click()
    time.sleep(1.5)

    rename = page.locator(".tooltip-item:has-text('重命名')")
    if rename.count() == 0:
        rename = page.locator("[class*=tooltip]:has-text('重命名')")
    if rename.count() == 0:
        rename = page.locator("text=重命名").last
    if rename.count() == 0 or not rename.first.is_visible(timeout=3000):
        print("   ⚠️ 未找到「重命名」选项")
        return False
    rename.first.click()
    time.sleep(1.5)

    dialog = page.locator(".el-dialog__wrapper:visible")
    inp = dialog.last.locator("input.el-input__inner")
    if inp.count() == 0:
        inp = dialog.last.locator("input[type='text']")
    if inp.count() == 0:
        print("   ⚠️ 未找到重命名输入框")
        return False
    inp.clear()
    time.sleep(0.3)
    inp.fill(new_name)
    time.sleep(0.5)

    confirm = dialog.last.locator("button:has-text('确定')")
    if confirm.count() > 0 and confirm.first.is_visible(timeout=3000):
        confirm.first.click()
        time.sleep(2)
        print(f"   ✅ 附件已重命名为: {new_name}")
        return True
    print("   ⚠️ 未找到重命名「确定」按钮")
    return False


def _upload_resume_to_51job(page, local_pdf_path: str, pdf_name: str) -> bool:
    """在 51job 简历中心上传 PDF 附件简历（满 3 份先腾位：只删非今日最旧，绝不删今日附件）。
    流程：sidebar 上传按钮 → 弹窗内 uploadBox_btn(expect_file_chooser) → 确认添加 → 重命名。
    因槽位无法安全腾出而放弃时，把结构化原因写入 _LAST_UPLOAD_BLOCK 供 deliver_job 回写失败日志。"""
    global _LAST_UPLOAD_BLOCK
    _LAST_UPLOAD_BLOCK = ""
    abs_path = os.path.abspath(local_pdf_path)
    print(f"   📄 准备上传简历: {os.path.basename(abs_path)} ({os.path.getsize(abs_path) / 1024:.0f} KB)")

    print("   🌐 导航到 51job 简历中心...")
    page.goto(RESUME_MANAGE_URL, wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)
    _close_popups(page)

    before_count = page.locator("div.myFile.resume").count()
    print(f"   📋 上传前附件数: {before_count}")

    # 2026-08-14 预警：列表为空常见于今日上传配额已耗尽（status=720721
    # 「今日上传次数达上限」）。不直接判死（新账号可能合法为空），
    # 继续尝试一次，以 add 业务响应为准
    if before_count == 0:
        print("   ⚠️ 附件列表为空：可能今日上传次数已达上限（51job 按日限次），尝试上传并以 add 响应确认")

    # 满 3 份先腾位：只删非今日最旧一份；全为今日附件则放弃（保护今日投递记录的附件绑定）
    if before_count >= ATTACH_LIMIT:
        print(f"   ⚠️ 附件简历已满 ({before_count}/{ATTACH_LIMIT})，尝试腾位...")
        if not _free_attachment_slot(page):   # 具体原因由腾位函数写入 _LAST_UPLOAD_BLOCK
            return False
        time.sleep(2)
        _safe_reload(page)
        time.sleep(5)  # 等待列表更新
        _close_popups(page)
        before_count = page.locator("div.myFile.resume").count()
        print(f"   📋 清理后附件数：{before_count}")
    
    # Step 1: 点 sidebar「上传附件简历」（Vue 未渲染完时重载重试，2026-08-14 加固）
    # 2026-08-24：按钮类名已由 mb16 变为 mb8（实测当前页面 HTML）；
    # 元素存在但不可见时（账号未创建在线简历/登录态异常）落诊断快照协助定位
    sidebar_btn = None
    for retry in range(3):
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        for sel in ["div.upload_btn.mb8", "div.upload_btn.mb16", "div.upload_btn", "text=上传附件简历"]:
            loc = page.locator(sel)
            if loc.count() > 0:
                try:
                    loc.first.scroll_into_view_if_needed()
                    time.sleep(1)
                except Exception:
                    pass
                if loc.first.is_visible(timeout=5000):
                    sidebar_btn = loc
                    break
        if sidebar_btn is not None:
            break
        print(f"   ⏳ 未找到上传按钮（页面可能未渲染完），重载重试 ({retry+1}/3)...")
        try:
            page.reload(wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)
            _close_popups(page)
        except Exception:
            time.sleep(5)
    if sidebar_btn is None:
        print("   ❌ 未找到 sidebar「上传附件简历」按钮")
        _dump_upload_diagnostics(page)
        return False

    # patch 截获 add 业务响应：必须放在上面所有可能的 reload（删旧腾位 / 找按钮重试）之后、
    # 点「确认添加」之前——2026-09-16 真机：补丁装在 reload 前被冲掉，120s 收不到响应把
    # 已成功的上传误判为失败（配额已耗却记为失败）
    add_patch = page.evaluate(JS_PATCH_ADD)
    if not add_patch.get("ok"):
        print(f"   ⚠️ add 响应截获 patch 失败：{add_patch.get('err')}（上传结果将退化为附件列表回查确认）")
        
    print("   🖱️ 点击上传按钮...")
    sidebar_btn.first.click()
    time.sleep(3)  # 等待弹窗和文件选择器准备
    
    # Step 2: 点弹窗内 uploadBox_btn，file_chooser 拦截选文件
    try:
        with page.expect_file_chooser(timeout=20000) as fc_info:
            dialog_btn = page.locator(".uploadBox_btn")
            if dialog_btn.count() == 0 or not dialog_btn.first.is_visible(timeout=8000):
                print("   ❌ 弹窗内 .uploadBox_btn 不可见")
                return False
            dialog_btn.first.click()
        fc_info.value.set_files(abs_path)
        print("      ✅ 文件已选择，开始解析中...")
        time.sleep(10)  # 关键！给 PDF 解析足够的时间（可能需要很久）
    except Exception as e:
        print(f"   ❌ 文件选择失败：{e}")
        return False
    
    # Step 3: 等待并点击「确认添加」按钮
    print("   ⏳ 等待 '确认添加' 按钮出现...")
    confirm_btn = None
    for _ in range(15):  # 最多等待 15 秒
        try:
            # 尝试多种 selector
            for sel in ["button:has-text('确认添加')", "text=确认添加"]:
                try:
                    candidate = page.locator(sel).first
                    if candidate.count() > 0 and candidate.is_visible(timeout=2000):
                        confirm_btn = candidate
                        break
                except:
                    continue
                
            if confirm_btn is not None:
                print("      ✅ '确认添加' 按钮已出现")
                break
        except:
            pass
            
        time.sleep(1)
        
    if confirm_btn is None or confirm_btn.count() == 0:
        print("   ❌ 长时间等待后仍未找到 '确认添加' 按钮")
        return False
        
    print("   🖱️ 点击「确认添加」...")
    confirm_btn.first.click()
    print("      ✅ 已提交上传，等待 add 业务响应（当前网络实测需 25~30s）...")

    # 2026-08-14：轮询等待 add 业务响应并校验，最多 120s。
    # 旧代码固定 sleep 8s 就认为成功，导致配额耗尽等失败被吞掉
    add_resp = None
    for _ in range(24):
        time.sleep(5)
        try:
            add_resp = page.evaluate("() => window.__addResp || null")
        except Exception:
            add_resp = None
        if add_resp:
            break

    if add_resp is None:
        # 兜底回查：截获不到响应不代表上传失败（补丁可能又被页面重载冲掉）。
        # 列表数量较清理后增长且出现「今日新传的同名附件」即判成功并补记配额。
        print("   ⚠️ 120s 内未收到 add 业务响应，回查附件列表兜底确认...")
        _safe_reload(page)  # 先刷新，确保读到服务端最新列表而非前端陈旧 DOM
        time.sleep(3)
        after_list = _get_attach_list(page)
        grew = len(after_list) > before_count
        matched_today = any(
            _name_matches(str(it.get("name", "")), pdf_name) and _is_today(it.get("createTime"))
            for it in after_list
        )
        if grew and matched_today:
            print(f"   ✅ 附件列表已新增今日「{pdf_name}」，判定上传成功（补记配额）")
            upload_quota.mark_upload_success()
        else:
            print("   ⚠️ 附件列表无今日新增，上传结果未知（按失败处理）")
            return False
    else:
        add_status = str(add_resp.get("status"))
        add_msg = add_resp.get("message") or ""
        if add_resp.get("threw"):
            print(f"   ❌ add 请求异常: {add_resp.get('threw')}")
            return False
        if add_status == "1":
            print(f"   ✅ add 业务确认成功（status=1）")
            upload_quota.mark_upload_success()
            time.sleep(3)
        else:
            print(f"   ❌ add 业务失败: status={add_status} message={add_msg}")
            if add_status == "720721":
                print("      ⛔ 今日上传次数已达上限——51job 对附件简历上传按日限次，请明日再传")
                upload_quota.mark_quota_exhausted()
            return False

    # 重命名为原 PDF 文件名：失败只告警不阻塞——2026-09-16 真机曾因三点菜单点击
    # 超时把「附件已上传成功」的岗位整岗判死（配额已耗、岗未投出）
    try:
        _rename_latest_attachment(page, pdf_name)
    except Exception as e:
        print(f"   ⚠️ 附件重命名失败（不阻塞，附件已上传成功）: {str(e)[:80]}")

    print(f"   🎉 上传完成!")
    return True


def _wait_until_reviewed_api(page, pdf_name: str) -> bool:
    """轮询 cupid center 接口，直到目标附件 status='01'(过审)。在岗位页调用。"""
    for i in range(REVIEW_POLL_TIMES):
        lst = _get_attach_list(page)
        for it in lst:
            if _name_matches(it.get("name", ""), pdf_name) and str(it.get("status")) == "01":
                print(f"   ✅ 附件「{pdf_name}」已审核通过")
                return True
        # 检查是否存在但仍在审核
        exists_reviewing = any(_name_matches(it.get("name", ""), pdf_name) for it in lst)
        if exists_reviewing:
            print(f"   ⏳ 附件「{pdf_name}」审核中，{REVIEW_POLL_INTERVAL}s 后重试 ({i+1}/{REVIEW_POLL_TIMES})...")
        else:
            print(f"   ⏳ 附件「{pdf_name}」尚未在列表中出现，{REVIEW_POLL_INTERVAL}s 后重试 ({i+1}/{REVIEW_POLL_TIMES})...")
        time.sleep(REVIEW_POLL_INTERVAL)
    print(f"   ⚠️ 等待审核超时，附件「{pdf_name}」可能仍在审核中")
    return False


def _delete_all_attachments(page) -> int:
    """彻底清空所有附件简历。
    策略：循环调用三点菜单→删除→确认，每次只删最旧的一份。
    关键点：每次检查前先多次刷新+等待，直到检测到至少 1 份附件才开始删除流程。
    """
    deleted_count = 0
    max_iterations = 15  # 增加最大次数以应对慢加载
    
    for iteration in range(max_iterations):
        print(f"      [迭代 {iteration+1}/{max_iterations}] 准备检查...")
        
        # 多次刷新 + 等待，直到检测到附件存在
        found_attachments = False
        for retry in range(3):  # 最多重试 3 次
            try:
                page.reload(wait_until="domcontentloaded", timeout=20000)
                time.sleep(3)
                        
                files_before = page.locator("div.myFile.resume").count()
                print(f"         刷新 {retry+1} 次：检测到 {files_before} 份")
                        
                if files_before > 0:
                    found_attachments = True
                    break
            except Exception as e:
                print(f"         ⚠️ 刷新失败 ({retry+1}): {str(e)[:60]}")
                time.sleep(2)
        
        if not found_attachments:
            print(f"      ⚠️ 连续 3 次刷新仍未检测到附件，可能已为空")
            return deleted_count
        
        # 找到附件，执行删除
        try:
            last_file = page.locator("div.myFile.resume").nth(files_before - 1)
            more_btn = last_file.locator(".moreIcon")
            
            if more_btn.count() == 0 or not more_btn.is_visible(timeout=8000):
                print(f"      ⚠️ 未找到删除按钮，可能是最后一份")
                break
            
            print(f"      🖱️ 点击最后 1 份 ({files_before}/{max_iterations}) 的删除操作...")
            more_btn.click()
            time.sleep(3.5)
            
        except Exception as e:
            print(f"      ❌ 点击失败：{e}")
            break
        
        # 点击「删除」选项
        delete_btn = None
        for sel in [".tooltip-item:has-text('删除')", "text=删除"]:
            try:
                candidate = page.locator(sel).first
                if candidate.count() > 0 and candidate.is_visible(timeout=8000):
                    delete_btn = candidate
                    break
            except:
                continue
        
        if delete_btn is None or delete_btn.count() == 0:
            print(f"      ⚠️ 未找到删除选项")
            break
        
        delete_btn.first.click()
        time.sleep(2.5)
        
        # 点击确定
        confirmed = False
        for sel in [
            ".el-message-box__btns button:has-text('确定')",
            ".el-dialog__wrapper:visible button:has-text('确定')",
            "button:has-text('确定删除')",
            "button:has-text('确定')",
        ]:
            try:
                btn = page.locator(sel).last
                if btn.count() > 0 and btn.is_visible(timeout=5000):
                    btn.click()
                    confirmed = True
                    time.sleep(5)  # 等待删除完成和页面完全更新
                    print(f"      ✅ 删除成功，等待页面更新...")
                    break
            except:
                continue
        
        if not confirmed:
            print(f"      ⚠️ 未找到确认按钮")
            break
        
        deleted_count += 1
        time.sleep(1)
        print(f"   └─ 当前累计删除：{deleted_count} 份")
    
    print(f"\n   🎯 清空完成！最终删除 {deleted_count} 份")
    return deleted_count


def _delete_attachment_api(page, att_id, att_name: str = "") -> bool:
    """cupid API 删除指定附件简历（删除不消耗日上传配额）。失败返回 False 由调用方决定回退。"""
    try:
        res = page.evaluate(JS_DELETE_ATTACH, str(att_id))
    except Exception as e:
        print(f"      ⚠️ API删除附件异常({att_name or att_id}): {str(e)[:80]}")
        return False
    if res.get("ok"):
        print(f"      ✅ 已删除(API): {att_name or att_id} (id={att_id})")
        return True
    print(f"      ⚠️ API删除失败({res.get('err') or res.get('msg')}): {att_name or att_id}")
    return False


def _free_attachment_slot(page) -> bool:
    """附件槽位已满时腾位：只删「非今日」上传的最旧一份。

    ⛔ 绝不删除今日上传的附件——今日附件可能已通过 modify-attach-resume 绑定到今日
    投递记录，删除会让投递记录的附件引用悬空、简历展示回退成默认附件（2026-09-16
    真机事故：精投「清场」删掉当日两份海投「我的简历」，两条海投投递记录的简历全部
    显示成精投简历）。槽位全被今日附件占满时宁可失败转人工，也不破坏已投岗位。
    """
    global _LAST_UPLOAD_BLOCK
    attach_list = _get_attach_list(page)
    if len(attach_list) < ATTACH_LIMIT:
        return True
    non_today = [it for it in attach_list if not _is_today(it.get("createTime"))]
    if not non_today:
        print(f"   ⛔ 附件槽位已满 {len(attach_list)}/{ATTACH_LIMIT} 且全部为今日上传，"
              f"删除将破坏今日已投岗位的附件绑定，转人工清理后重试")
        _LAST_UPLOAD_BLOCK = SLOTS_FULL_TODAY_ERROR
        return False
    victim = min(non_today, key=lambda it: str(it.get("createTime") or ""))
    print(f"   🧹 腾位：删除非今日最旧附件「{victim.get('name')}」(id={victim.get('id')}, "
          f"createTime={victim.get('createTime')})...")
    if _delete_attachment_api(page, victim.get("id"), victim.get("name", "")):
        return True
    # API 删除失败即保守放弃（不回退按 DOM 顺序的 UI 删除——DOM 顺序无法保证被删的是非今日附件，
    # 任何「可能删到今日附件」的路径都禁止）
    print("   ⛔ API 腾位失败，保守放弃上传（绝不冒险删除今日附件），转人工处理")
    _LAST_UPLOAD_BLOCK = SLOT_FREE_FAILED_ERROR
    return False


# ==========================================
# 投递后附件挂接（2026-08-14 新增）
# ==========================================

def _attach_resume_to_apply(page, cv_log_ids: list, apply_popup: dict, pdf_name: str,
                              target_id=None, job_url: str = "") -> bool:
    """投递成功后把附件简历挂接到本次投递（等价于 UI 「补充附件」弹窗点确认）。

    2026-08-14 修复：light-apply-job 默认只发在线简历，附件必须用
    cvLogIdList + attachResumeId 调 modify-attach-resume 才能挂上。
    优先按名字/target_id 从 popupAttachResumeList 匹配目标附件；若响应无 popup 则直接复用已锁定的 target_id。
    """
    if not cv_log_ids:
        print("   ⚠️ 未拿到 cvLogId，无法挂接附件（可能是历史已投递）")
        return False
    popup = apply_popup or {}
    attach_items = popup.get("attachResumeList") or []

    chosen = None
    for it in attach_items:
        if _name_matches(str(it.get("name", "")), pdf_name):
            chosen = it
            break
    if chosen is None and target_id:
        chosen = next((it for it in attach_items if str(it.get("attachResumeId", "")) == str(target_id)), None)
    if chosen is None and len(attach_items) == 1:
        chosen = attach_items[0]

    if chosen is not None:
        attach_id = chosen.get("attachResumeId") or chosen.get("id")
        attach_display_name = chosen.get("name", pdf_name)
    elif target_id:
        # 响应中未带 popup 列表但目标附件 ID 已明确，直接使用目标 ID
        attach_id = str(target_id)
        attach_display_name = pdf_name
    else:
        print(f"   ⚠️ 无法确定目标附件 ID，放弃挂接防止挂错附件")
        return False

    print(f"   6. 挂接附件「{attach_display_name}」(id={attach_id}) 到本次投递...")
    payload = {"cvLogIdList": cv_log_ids, "attachResumeId": str(attach_id)}

    # 解除任何可能限制子域名导航的路由拦截
    try:
        page.unroute("**/*")
    except Exception:
        pass

    for attempt in (1, 2):
        try:
            # 简历中心全局稳定挂载 Vue 及 cupid axios 实例，不受详情页跳转影响
            if "resume/center" not in page.url:
                page.goto(RESUME_MANAGE_URL, wait_until="domcontentloaded", timeout=30000)
                time.sleep(3)
                _close_popups(page)
            res = page.evaluate(JS_ATTACH_RESUME, payload)
        except Exception as e:
            res = {"ok": False, "err": str(e)[:120]}
        if res.get("ok") and str(res.get("status")) == "1":
            print("      ✅ 附件挂接成功！雇主将收到在线简历 + 附件简历")
            return True
        print(f"      ⚠️ 第 {attempt} 次挂接未成功: {json.dumps(res, ensure_ascii=False)[:200]}")
        time.sleep(2)
    print("      ❌ 附件挂接两次均失败")
    return False


# ==========================================
# 投递主入口
# ==========================================

def deliver_job(job_data: dict) -> bool:
    """
    51job 确定性精准投递入口。

    Args:
        job_data: {
            "record_id":  飞书记录 ID,
            "job_url":    岗位链接,
            "file_token": PDF 备份 token,
            "pdf_name":   简历名(=附件名，格式 {公司}_{岗位}),
            "mass_apply": 是否海投（True 时附件固定为「我的简历」，每日仅上传一次、当日复用）,
            "batch_mass_uploaded": 编排层告知本批次此前已成功海投（仅作日志参考，不再作为新鲜度依据）,
            "greeting":   (51job 不使用),
            "image_items": (51job 不使用),
        }
    Returns:
        bool: 投递是否成功（成功=目标附件已确定同步到该投递）。
        今日附件上传配额已耗尽（720721）且本岗确需新上传时，失败日志写
        upload_quota.QUOTA_EXHAUSTED_ERROR（[风控] 前缀，当日波次不再重试、次日自动恢复）。
    """
    job_url = job_data.get("job_url", "")
    record_id = job_data.get("record_id", "")
    file_token = job_data.get("file_token", "")
    mass_apply = bool(job_data.get("mass_apply", False))
    if mass_apply:
        pdf_name = MASS_RESUME_NAME  # 51job 海投模式固定名称为「我的简历」
    else:
        pdf_name = job_data.get("pdf_name") or job_data.get("temp_pdf_name") or "专属定制简历"
    global _MASS_FORCE_UPLOAD

    def _log_error(msg: str):
        print(f"   ❌ {msg}")
        job_data["delivery_error"] = str(msg)
        if record_id:
            try:
                update_feishu_record(record_id, {"自动投递失败日志": str(msg)[:120]})
            except Exception:
                pass

    if not job_url:
        _log_error("[物料] 缺少岗位链接")
        return False
    
    if not file_token:
        _log_error("[物料] 缺少 PDF 备份附件，51job 精准投递需要附件简历")
        return False

    from app.automation.abort import is_job_delivery_cancelled
    if is_job_delivery_cancelled(record_id):
        print(f"🛑 [51job] 投递前检测到岗位 {record_id} 已被用户终止，立即退出")
        _log_error("[用户主动终止] 在指挥中心手动终止投递流程")
        return False

    print(f"\n🚀 [51job 精准投递引擎] 启动 | 目标: {job_url} | 附件: {pdf_name}")

    os.makedirs(TEMP_DIR, exist_ok=True)
    local_pdf_path = os.path.join(TEMP_DIR, f"{pdf_name}.pdf")
    delivery_ok = False
    sent_id = None
    sent_name = None

    with sync_playwright() as p:
        page = None
        browser = None
        try:
            browser, context = _connect_browser(p)
            page = context.new_page()

            try:
                from app.automation.delivery_interrupter import register_delivery_target, make_page_interrupt_fn
                register_delivery_target(record_id, make_page_interrupt_fn(lambda: page))
            except Exception:
                pass

            # Step 1: 打开岗位详情页
            print("   1. 打开岗位详情页...")
            page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(4)
            _close_popups(page)
            print(f"      标题: {page.title()}")
            # 登录态失效 / 滑动验证：立即结构化止损，不再空耗后续上传与投递流程
            login_block = _detect_login_block(page)
            if login_block:
                _log_error(login_block)
                return False
            page_company, page_title = _extract_job_info_from_page(page)
            if page_company and page_title:
                print(f"      页面: 公司={page_company} | 岗位={page_title}")
                if not mass_apply and not _attachment_name_matches_job(pdf_name, page_company, page_title):
                    print("      ⚠️ 附件名与岗位页信息不完全匹配（仅告警，以岗位链接为准继续）")
            # Step 1.5: 上传前预检——在任何附件上传之前：
            #   已投过（detailData.isApply）→ 幂等成功，不白烧配额（Step 5 仍保留兜底幂等分支）；
            #   正文明示已下线，或（无投递组件 且 公司/岗位信息两者皆缺，标题仅「招聘 | 前程无忧」）
            #   → 岗位已下架/失效，[下架] 止损；只缺其一视为慢加载，交给后续步骤自行重试
            component_found, already_applied = _check_already_applied(page)
            if component_found and already_applied:
                print("   1.5 ℹ️ 岗位此前已投递（detailData.isApply），幂等视为成功，跳过上传与投递")
                _mark_delivered_in_feishu(record_id, "（上传前幂等预检）")
                return True
            if _page_says_offline(page) or (not component_found and not (page_company or page_title)):
                _log_error(JOB_PAGE_INVALID_ERROR)
                return False

            if is_job_delivery_cancelled(record_id):
                print(f"🛑 [51job] 打开岗位后检测到岗位 {record_id} 已被用户终止，立即退出")
                _log_error("[用户主动终止] 在指挥中心手动终止投递流程")
                return False

            # Step 2: 读附件列表，定位目标附件
            print("   2. 读取附件列表...")
            attach_list = _get_attach_list(page)
            
            # Step 2.5: ★★ 海投策略——51job 附件上传按日限次，「我的简历」每天只传一次，
            # 当日后续海投岗位（跨批次、跨波次、跨进程）一律复用；非当日上传的远端同名
            # 旧简历不复用（防止投出陈旧母本）。executor 新批量任务显式 reset 时强制重传。
            if mass_apply:
                # 先精确名匹配（远端可能有同名 V2 前缀版本），再前缀匹配
                existing = next(
                    (it for it in attach_list if str(it.get("name", "")) == pdf_name), None,
                ) or next(
                    (it for it in attach_list if _name_matches(it.get("name", ""), pdf_name)), None,
                )
                # 当日新鲜度双信号（均带日期校验）：本地配额标记（跨批次/波次有效）+ 远端 createTime。
                # 2026-09-16 真机：本地标记因后续步骤异常没写上时，靠远端信号避免重复烧配额。
                # 编排层传入的 batch_mass_uploaded 不再作为新鲜度依据：首岗幂等早退（未真实上传）
                # 也会让它置位，会把往日旧附件误判为今日新鲜（第 5 轮审查 P1）。
                remote_today = bool(existing and _is_today(existing.get("createTime")))
                if remote_today:
                    upload_quota.mark_mass_resume_uploaded_today()
                fresh_today = upload_quota.is_mass_resume_fresh_today() or remote_today
                if _MASS_FORCE_UPLOAD and not upload_quota.is_exhausted_today():
                    print(f"   2.5 新批量任务要求刷新海投母本：强制重传「{pdf_name}」")
                    target = None
                elif existing is not None and fresh_today:
                    target = existing
                    if _MASS_FORCE_UPLOAD:
                        print(f"   2.5 今日上传配额已耗尽，无法刷新母本，退回复用今日已上传的「{target.get('name')}」")
                        _MASS_FORCE_UPLOAD = False  # 次日新鲜度自然失效会触发重传，无需保留强制标志
                    else:
                        print(f"   2.5 [海投当日复用] 「{target.get('name')}」(id={target.get('id')}) 为今日已上传版本，直接复用跳过上传")
                elif existing is not None:
                    print(f"   2.5 列表中的「{existing.get('name')}」并非今日上传，重传当日最新版（每日仅此一次）")
                    target = None
                else:
                    print(f"   2.5 列表中无「{pdf_name}」，执行今日首次海投上传...")
                    target = None
            else:
                # 非海投模式：查找已有的过审同名附件即复用（不要求今日）——精投附件名 {公司}_{岗位}
                # 每岗唯一，命中只可能是同岗位此前重试留下的同一份定制简历，复用不耗配额且内容一致
                target = next(
                    (it for it in attach_list if _name_matches(it.get("name", ""), pdf_name) and str(it.get("status")) == "01"),
                    None,
                )

            # Step 3: 目标不存在/未过审 → 清理同名旧附件 + 下载 PDF + 上传(满3份先腾位) + 等过审
            if target is None:
                # 「确需上传」决策点：今日已撞 720721 则此处止损（附件可复用的岗位不受影响）
                if upload_quota.is_exhausted_today():
                    _log_error(upload_quota.QUOTA_EXHAUSTED_ERROR)
                    return False
                # 上传前先删同名「非今日」旧附件：51job 对同名附件自动加 V1/V2 后缀，不先删
                # 旧版既堆槽位又让名字漂移（2026-09-16 真机残留 我的简历V1/V2）；今日同名附件
                # 不删（海投当日复用在 Step 2.5 已处理；精投当日重试则保留待审核那份）
                stale_same_name = [
                    it for it in attach_list
                    if _name_matches(str(it.get("name", "")), pdf_name) and not _is_today(it.get("createTime"))
                ]
                for it in stale_same_name:
                    print(f"   3. 清理同名旧附件「{it.get('name')}」(id={it.get('id')}, createTime={it.get('createTime')})...")
                    _delete_attachment_api(page, it.get("id"), it.get("name", ""))
                if stale_same_name:
                    attach_list = [it for it in attach_list if it not in stale_same_name]
                print(f"   3. 目标附件「{pdf_name}」不存在或未过审，执行上传...")
                if not download_feishu_file(file_token, local_pdf_path) or not os.path.exists(local_pdf_path):
                    _log_error("飞书 PDF 备份下载失败")
                    return False
                print(f"      ✅ PDF 下载成功: {os.path.getsize(local_pdf_path)/1024:.1f} KB")

                if not _upload_resume_to_51job(page, local_pdf_path, pdf_name):
                    # 简历中心被重定向到登录页时岗位页未必暴露登录态失效，此处再查一次
                    login_block = _detect_login_block(page)
                    if upload_quota.is_exhausted_today():
                        _log_error(upload_quota.QUOTA_EXHAUSTED_ERROR)
                    elif _LAST_UPLOAD_BLOCK:
                        _log_error(_LAST_UPLOAD_BLOCK)
                    elif login_block:
                        _log_error(login_block)
                    else:
                        _log_error("附件简历上传失败")
                    return False
                if mass_apply:
                    upload_quota.mark_mass_resume_uploaded_today()
                    _MASS_FORCE_UPLOAD = False
                
                if mass_apply:
                    print(f"   3.4 海投模式：回岗位页并等待新附件过审，以拿到可挂接的附件 ID...")
                    time.sleep(3)  # 给页面一点缓冲时间
                    _safe_goto(page, job_url, timeout=60000)
                    time.sleep(8)
                    _close_popups(page)
                    # 2026-09-16 真机：不等过审 → 新附件无 ID → Step 6 放弃挂接 → 雇主只收到在线简历
                    _wait_until_reviewed_api(page, pdf_name)
                else:
                    # 非海投模式：回到岗位页 (已验证该页 cupid 可用)，轮询直到过审
                    _safe_goto(page, job_url, timeout=30000)
                    time.sleep(4)
                    _close_popups(page)
                    _wait_until_reviewed_api(page, pdf_name)

                attach_list = _get_attach_list(page)
                # 海投允许回退到「今日上传但仍审核中」的同名附件，确保 Step 6 有 ID 可挂
                target = _pick_target_attachment(attach_list, pdf_name, allow_unreviewed_today=mass_apply)
            else:
                if mass_apply:
                    print(f"   3. 同一任务复用已过审的「{pdf_name}」，跳过上传")
                else:
                    print(f"   3. 目标附件已存在且过审，跳过上传")
            
            # 清理本地临时文件
            try:
                if os.path.exists(local_pdf_path):
                    os.remove(local_pdf_path)
            except Exception:
                pass
            
            # 海投模式下，如果上传了新简历但没有在列表中显示（仍在审核），直接用刚上传的 resume
            if mass_apply and target is None:
                target_id = None
                target_name = pdf_name  # 直接使用 PDF 文件名
                print(f"   🎯 海投模式：使用刚上传的「{target_name}」（可能仍在审核中）")
                # 关键：海投模式下强制刷新岗位页，确保附件选择器能读取到最新列表
                if job_url in page.url:
                    _safe_reload(page)
                    time.sleep(5)
                    _close_popups(page)
            elif target is None:
                _log_error(f"附件列表中没有可用的「{pdf_name}」(可能审核未通过)")
                return False
            else:
                target_id = str(target.get("id"))
                target_name = target.get("name")
                print(f"      🎯 目标附件：id={target_id} | name={target_name}")

            # Step 3.5: 附件列表体检（只看不删）。
            # ⛔ 不再执行「清场只留目标」：Step 6 用 attachResumeId 精确挂接，无需列表唯一；
            # 而删除其他附件会让当日已投岗位的附件引用悬空（2026-09-16 真机：精投清场删掉
            # 当日海投「我的简历」，两条海投投递记录的简历全部回退显示为精投简历）
            final_check = _get_attach_list(page)
            print(f"   3.5 附件列表体检：共 {len(final_check)} 份（不清理其他附件，保护已投岗位的附件绑定）")
            if mass_apply and not target_id:
                # 双保险回填：体检列表里已能看到刚上传的同名附件时补上 ID，避免 Step 6 无 ID 放弃挂接
                backfill = _pick_target_attachment(final_check, pdf_name, allow_unreviewed_today=True)
                if backfill is not None:
                    target_id, target_name = str(backfill.get("id")), backfill.get("name") or pdf_name
                    print(f"   3.5 回填海投目标附件 ID：{target_id}（{target_name}）")
            for att in final_check:
                status_icon = "✅" if str(att.get('status')) == '01' else "⏳"
                marker = " ← 本次目标" if target_id and str(att.get('id')) == str(target_id) else ""
                print(f"      {status_icon} {att.get('name')} (id={att.get('id')}, status={att.get('status')}, createTime={att.get('createTime')}){marker}")
            if mass_apply and not target_id:
                print(f"   3.5 海投模式：新上传简历「{target_name}」尚未在列表出现，直接去投递（挂接将依赖投递响应中的附件候选）...")
            # 体检读接口不导航；此处兜底回到岗位页
            if job_url not in page.url:
                _safe_goto(page, job_url, timeout=30000)
                time.sleep(4)
                _close_popups(page)

            # Step 4: patch cupid.post 截获 cvLogId + 拦截成功页跳转
            # PCApplyJob 组件可能懒加载/挂载慢，重试等待
            print("   4. 准备截获 cvLogId（patch cupid.post）...")
            setup = {"ok": False, "err": "not tried"}
            for _try in range(15):  # 增加到 15 次，每次等 3 秒
                setup = page.evaluate(JS_SETUP_PATCH)
                if setup.get("ok"):
                    print(f"      ✅ Patch 成功 ({_try+1}/15)")
                    break
                print(f"      ⏳ Patch 尝试 {_try+1}: {setup.get('err') or '等待中'}")
                time.sleep(3)  # 更长的间隔
            if not setup.get("ok"):
                print(f"   ⚠️ 初次 patch 失败：{setup.get('err')}，尝试重新进入岗位页...")
                # 重新导航到岗位页试试
                _safe_reload(page, timeout=90000)
                time.sleep(10)
                _close_popups(page)
                # 再试一次 patch
                for _try in range(5):
                    setup = page.evaluate(JS_SETUP_PATCH)
                    if setup.get("ok"):
                        print(f"      ✅ Reload 后 patch 成功")
                        break
                    time.sleep(3)
            
            if not setup.get("ok"):
                _log_error(f"无法定位 PCApplyJob/cupid: {setup.get('err')} (尝试了多次)")
                return False
            # 拦截跨域导航（防意外跳走），但同源导航必须放行：
            # 2026-08-14 实测 abort 所有导航会把点击后的同源跳转打死（页面挂起，
            # light-apply-job 请求发不出去，两岗全部 failed）；cvLogId 改由
            # 网络层 page.on("response") 截获，不再依赖拦截同源重载
            def _route_guard(route):
                req = route.request
                if req.is_navigation_request():
                    try:
                        req_host = urlparse(req.url).netloc
                        # 放行 51job 旗下所有子域名（jobs / we / www / cupid / login）
                        if req_host and "51job.com" in req_host:
                            return route.continue_()
                        cur_host = urlparse(page.url).netloc
                        if req_host and cur_host and req_host != cur_host and "51job.com" not in req_host:
                            return route.abort()
                    except Exception:
                        pass
                return route.continue_()
            page.route("**/*", _route_guard)

            # Step 5: 投递——优先 JS 层直接调 applyJobFun（响应必达，不触发重载），
            # 失败再回退点按钮 + 网络层截获
            print("   5. 投递（JS 直接调用 applyJobFun）...")
            apply_resp = None
            cv_log_ids = []
            apply_popup = None
            delivery_ok = False
            try:
                direct = page.evaluate(JS_DIRECT_APPLY)
            except Exception as e:
                direct = {"ok": False, "err": f"evaluate异常: {str(e)[:100]}"}
            if direct.get("isApply"):
                # 幂等处理：岗位此前已投递过 = 目标已达成，按成功收尾并同步飞书，
                # 避免重复投递被误判为失败（重试只会再次命中 isApply 死循环）
                print("      ℹ️ 岗位已是已投递状态（detailData.isApply），幂等视为成功")
                _mark_delivered_in_feishu(record_id)
                return True
            if direct.get("ok") and direct.get("cvLogIds"):
                cv_log_ids = direct["cvLogIds"]
                apply_popup = direct.get("popup")
                apply_resp = {"status": direct.get("status"), "message": direct.get("message")}
                delivery_ok = True
                sent_id = target_id
                sent_name = target_name
                print(f"      ✅ 直接投递成功！cvLogId={cv_log_ids[0]}" +
                      ("，响应含补充附件弹窗候选" if apply_popup else "，响应无附件弹窗数据"))
            elif direct.get("ok") and str(direct.get("status")) == "1":
                delivery_ok = True
                sent_id = target_id
                sent_name = target_name
                print(f"      ✅ 直接投递成功（status=1，但无 cvLogId，附件无法挂接） raw={direct.get('raw', '')[:200]}")
            else:
                print(f"      ⚠️ 直接调用失败({direct.get('err')})，回退点按钮流程...")

            if not delivery_ok and apply_resp is None:
                # ===== 回退：点按钮 + 网络层截获 =====
                apply_btn = page.locator(".apply-btn-new").first
                # 2026-08-14：投递前状态预检——已投递的岗位点不动按钮，
                # 避免盲点后误判成功（旧版因此把历史已投岗位当成本轮投递成功）
                try:
                    pre_text = apply_btn.inner_text(timeout=3000)
                    if "已投递" in pre_text or "申请记录" in pre_text:
                        _log_error(f"岗位已是【{pre_text.strip()}】状态，此前已投递（可能仅在线简历），本轮跳过")
                        return False
                except Exception:
                    pass
                # 网络层截获——CDP 层监听 light-apply-job 响应（回退路径下 XHR 可能被
                # 同源重载 abort，截获不到属正常，仅尽力而为）
                captured = {"resp": None, "cv_log_ids": [], "popup": None}
                def _on_apply_response(resp):
                    try:
                        if "light-apply-job" not in resp.url:
                            return
                        body = resp.json()
                        rb = (body or {}).get("resultbody") or {}
                        lst = (rb.get("applyJobResult") or {}).get("applySuccessJobList") or []
                        captured["resp"] = body
                        captured["cv_log_ids"] = [x.get("cvLogId") for x in lst if x.get("cvLogId")]
                        captured["popup"] = rb.get("popupAttachResumeList")
                    except Exception:
                        pass
                page.on("response", _on_apply_response)

                # 多次滚动和检查确保按钮可见
                for _ in range(3):
                    try:
                        apply_btn.scroll_into_view_if_needed()
                        time.sleep(0.5)
                        btn_visible = apply_btn.is_visible(timeout=2000)
                        if btn_visible:
                            break
                    except:
                        pass
                print("      🖱️ 点击按钮...")
                apply_btn.click(force=True)
                print("      ✅ 已点击，等待 light-apply-job 响应...")

                print("      ⏳ 等待 up to 30s 截获 light-apply-job 响应（网络层监听）...")
                for wait_try in range(30):  # 每次 1 秒
                    time.sleep(1)
                    if captured["resp"] is not None:
                        apply_resp = captured["resp"]
                        cv_log_ids = captured["cv_log_ids"]
                        apply_popup = captured["popup"]
                        break
                    # 每 5 秒打印一次按钮状态（包异常：上下文销毁不影响网络层截获）
                    if (wait_try + 1) % 5 == 0:
                        try:
                            btn_state = apply_btn.inner_text(timeout=2000)
                        except Exception:
                            btn_state = "unknown"
                        print(f"         [等待 {wait_try+1}s] 按钮状态：{btn_state}...")
                if apply_resp is None and captured["resp"] is not None:
                    apply_resp = captured["resp"]
                    cv_log_ids = captured["cv_log_ids"]
                    apply_popup = captured["popup"]

            if delivery_ok:
                pass  # 已通过按钮状态确认
            elif apply_resp is None:
                # 30s 未截获响应：兑底重查岗位页按钮/成功页 URL（投递可能已发生）
                _fb_ok = False
                try:
                    cur_url = (page.url or "").lower()
                    if "applysuccess" in cur_url or "apply_success" in cur_url:
                        print(f"      ✅ 已在投递成功页，确认投递成功（但无 cvLogId，附件无法挂接）")
                        _fb_ok = True
                    else:
                        page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
                        time.sleep(5)
                        btn_text = page.locator(".apply-btn-new").first.inner_text(timeout=5000)
                        if "已投递" in btn_text:
                            print(f"      ✅ 兑底复查按钮已是【{btn_text}】，确认投递成功（但无 cvLogId，附件无法挂接）")
                            _fb_ok = True
                except Exception:
                    pass
                if _fb_ok:
                    delivery_ok = True
                    sent_id = target_id
                    sent_name = target_name
                else:
                    _log_error("30s 内未截获 light-apply-job 响应且复查无已投递状态（按钮可能未触发投递）")
                    return False
            else:
                status = apply_resp.get("status")
                print(f"      light-apply-job status={status} message={apply_resp.get('message')}")
                            
                # 检查是否有 cvLogId - 只要有说明投递发生了
                if cv_log_ids and len(cv_log_ids) > 0:
                    print(f"      ✅ 已获取到 cvLogId: {cv_log_ids[0]}")
                    delivery_ok = True
                    sent_id = target_id
                    sent_name = target_name
                    print(f"      ✅ 投递成功！（可能已在其他时间投递过同一个岗位）")
                elif str(status) == "1":
                    # 传统成功情况
                    delivery_ok = True
                    sent_id = target_id
                    sent_name = target_name
                    print(f"      ✅ 投递成功！随后按 attachResumeId 精确挂接「{target_name}」(id={target_id})")
                else:
                    # 既没有 cvLogId 也不是标准成功状态
                    _log_error(f"投递未成功 (status={status}, cvLogIds={cv_log_ids}): {json.dumps(apply_resp, ensure_ascii=False)[:400]}")
                    return False

            # Step 6: 把附件简历挂接到本次投递（2026-08-14 修复：light-apply 只发在线简历）
            if delivery_ok:
                if not _attach_resume_to_apply(page, cv_log_ids, apply_popup,
                                               target_name or pdf_name, target_id, job_url):
                    # 投递本身已成功，附件未挂上只标记提醒，不改投递结果
                    _log_error(f"【待补挂附件】投递成功但附件简历未挂接 (cvLogIds={cv_log_ids})")

        except Exception as exc:
            _log_error(f"投递异常中断: {str(exc)[:120]}")
            return False
        finally:
            try:
                from app.automation.delivery_interrupter import unregister_delivery_target
                unregister_delivery_target(record_id)
            except Exception:
                pass
            try:
                if page is not None:
                    page.close()
            except Exception:
                pass
            try:
                if browser is not None:
                    browser.close()
            except Exception:
                pass

    # Step 7: 回写飞书
    if delivery_ok:
        print(f"   7. 回写飞书：跟进状态=已投递，投递日期=今天 (附件={sent_name} id={sent_id})")
        if record_id:
            try:
                update_feishu_record(record_id, {
                    "跟进状态": "已投递",
                    "投递日期": int(time.time() * 1000),
                    "自动投递失败日志": "",
                })
                print("      ✅ 飞书已回写")
            except Exception as e:
                print(f"      ⚠️ 飞书回写失败: {e}")
        print("   🎉 51job 精准投递完成！")
        return True
    return False


if __name__ == "__main__":
    # 本地自测：从飞书拉一条 51job 待投递岗位跑完整链路
    from app.services.feishu_service import get_jobs_to_deliver
    jobs = get_jobs_to_deliver(target_platform="51job", target_status="待投递")
    if not jobs:
        print("无待投递 51job 岗位")
        sys.exit(0)
    test_job = jobs[0]
    print(f"🧪 自测目标: {test_job.get('company')} - {test_job.get('job_title')}")
    result = deliver_job(test_job)
    print(f"结果: {'成功' if result else '失败'}")
