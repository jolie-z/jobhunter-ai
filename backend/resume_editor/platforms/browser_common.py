"""
浏览器连接公共逻辑（所有平台统一）

硬性规则：所有自动化必须共用同一套 Edge 端口和 cookie，只需登录一次；
绝不允许启动新浏览器，绝不允许弹出 Chrome。

端口唯一来源：主后端 backend/app/session/registry.py（全项目唯一端口配置区），
通过 get_platform_port() 读取，禁止在脚本里硬编码端口。

DrissionPage 的 ChromiumOptions.set_local_port 在端口无响应时会尝试自动拉起
浏览器（默认路径是 Chrome），这正是"谷歌浏览器被弹出"的根因。本模块统一：
1. 连接前先探测 CDP 端口，无响应 → 抛 RuntimeError（提示先启动 Edge），绝不自动拉起；
2. ChromiumOptions 显式 set_browser_path(Edge)，作为双保险。
"""
import json
import os
import sys
import time
import urllib.request

EDGE_PATH = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"

# platforms/ → resume_editor/ → backend/
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 智联在线简历 Vuex store 的内容填充状态：
#   'yes'   = currentResume 存在，resumeId 有效 (>0) 且至少一个业务节点有实际内容（Profile 需包含非空姓名，经历列表非空）
#   'empty' = currentResume 存在且 resumeId 有效，但业务节点全空（真·空简历）
#   'no'    = store/currentResume 尚未就绪，或 resumeId 仍为 0，或仅有未填充的空壳占位
# store 对象先于业务数据出现——只等对象会读到全空壳（2026-08-31 / 2026-09-01 智联白纸事故根因：
# 页面刚开启时 resumeId=0 且 Profile 仅含空对象占位 [{}]，误判为已加载会导致生成全量 add 污染官网）。
# 读官网简历前一律先等本状态进入 yes/empty。
JS_RESUME_FILLED_STATE = r"""
return (function(){
    var root = document.querySelector('#root');
    if (!root || !root.__vue__) return 'no';
    var store = root.__vue__.$store;
    var rs = (store && store.state) ? store.state.resume : null;
    if (!rs || !rs.currentResume) return 'no';
    var rl = (rs.resumeList && rs.resumeList[rs.resumeIndex]) ? rs.resumeList[rs.resumeIndex] : null;
    var resumeId = rl ? (rl.resumeId || 0) : 0;
    if (!resumeId) return 'no';

    var cr = rs.currentResume;
    var hasValidProfile = false;
    if (cr.Profile && cr.Profile.length > 0) {
        var p0 = cr.Profile[0] || {};
        if (String(p0.name || '').trim()) hasValidProfile = true;
    }

    var hasOtherNodes = false;
    var keys = ['WorkExperience', 'EducationExperience', 'ProjectExperience',
                'TrainExperience', 'LanguageSkill', 'ProfessionalSkill', 'Certificate',
                'SelfEvaluate', 'UnifiedPurpose'];
    for (var i = 0; i < keys.length; i++) {
        if (cr[keys[i]] && cr[keys[i]].length > 0) {
            hasOtherNodes = true;
            break;
        }
    }
    if (hasValidProfile || hasOtherNodes) return 'yes';
    return 'empty';
})();
"""


def wait_resume_filled(page, tries: int = 20, interval: float = 1.0) -> str:
    """轮询等待智联简历内容节点填充。返回最终状态 'yes'/'empty'/'timeout'。

    超时返回 'timeout'（疑似软拦截/网络异常，调用方应中止而不是拿空数据继续）。
    """
    state = "timeout"
    for _ in range(tries):
        try:
            state = page.run_js(JS_RESUME_FILLED_STATE)
        except Exception:
            state = "no"
        if state in ("yes", "empty"):
            return state
        time.sleep(interval)
    return "timeout"


def get_platform_port(platform: str) -> int:
    """从全项目唯一端口配置区（backend/app/session/registry.py）读取平台调试端口。"""
    if _BACKEND_DIR not in sys.path:
        sys.path.insert(0, _BACKEND_DIR)
    from app.session.registry import get_platform_port as _port
    return _port(platform)


def get_platform_profile(platform: str) -> str:
    """从全项目唯一配置区（registry）读取平台持久化 profile 目录。

    端口和 profile 必须成对来自 registry：同一端口挂不同 profile 时，谁先启动谁的
    登录态生效，另一个入口就会"未登录"——各脚本曾经的私有 profile 目录正是
    「登录总是掉」的根因之一（登录写进 A 目录，主链路用的是 registry 目录）。
    """
    if _BACKEND_DIR not in sys.path:
        sys.path.insert(0, _BACKEND_DIR)
    from app.session.registry import get_profile_path
    return get_profile_path(platform)


_no_proxy_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def ensure_port_ready(port: int, timeout: float = 2.0) -> None:
    """端口必须已有浏览器在监听（CDP /json 有响应）才能继续。

    无响应时抛 RuntimeError，禁止后续 ChromiumPage 自动拉起浏览器。
    """
    try:
        _no_proxy_opener.open(f"http://127.0.0.1:{port}/json", timeout=timeout)
    except Exception as e:
        raise RuntimeError(
            f"Edge 浏览器未启动（端口 {port} 无 CDP 响应）。"
            f"请先在页面点击「启动」打开 Edge 并登录，再执行回写/采集。原始错误: {e}"
        ) from e


def make_options(port: int):
    """ChromiumOptions：固定调试端口 + 显式指定 Edge 可执行路径（双保险）。"""
    from DrissionPage import ChromiumOptions

    co = ChromiumOptions()
    co.set_local_port(port)
    if os.path.exists(EDGE_PATH):
        co.set_browser_path(EDGE_PATH)
    return co


def connect_page(port: int):
    """统一入口：先探测端口（无响应即报错，绝不自动拉起浏览器），再连接 ChromiumPage。"""
    from DrissionPage import ChromiumPage

    ensure_port_ready(port)
    return ChromiumPage(make_options(port))


# 弹窗自动关闭：只点弹窗右上角的 × 关闭图标（或 ESC 兜底），
# 绝不点击弹窗内「同步/确认」类语义按钮，避免污染官网数据。
JS_DISMISS_POPUP = r"""
return (function(marker){
  try {
    var hit = Array.prototype.filter.call(document.querySelectorAll('*'), function(el){
      return el.childElementCount === 0 && (el.textContent || '').indexOf(marker) >= 0;
    });
    if (!hit.length) return 'no-popup';
    var root = hit[0];
    for (var i = 0; i < 10 && root.parentElement; i++) {
      root = root.parentElement;
      var cs = window.getComputedStyle(root);
      if (cs.position === 'fixed' || cs.position === 'absolute') break;
    }
    var rr = root.getBoundingClientRect();
    var best = null;
    Array.prototype.forEach.call(root.querySelectorAll('*'), function(el){
      var r = el.getBoundingClientRect();
      if (r.width < 10 || r.width > 64 || r.height < 10 || r.height > 64) return;
      // 只认弹窗右上象限的小图标，远离底部「同步」按钮
      if (r.x < rr.x + rr.width * 0.6 || r.y > rr.y + rr.height * 0.4) return;
      var cls = '';
      try { cls = String(el.className.baseVal !== undefined ? el.className.baseVal : el.className); } catch(e) {}
      if (el.tagName === 'svg' || el.tagName === 'I' || el.tagName === 'BUTTON' || /close|icon/i.test(cls)) {
        if (!best || r.y < best.y) best = {x: r.x + r.width / 2, y: r.y + r.height / 2, y: r.y};
      }
    });
    if (best) {
      var el = document.elementFromPoint(best.x, best.y);
      if (el) { el.dispatchEvent(new MouseEvent('click', {bubbles: true})); return 'clicked'; }
    }
    document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', keyCode: 27, bubbles: true}));
    return 'esc';
  } catch(e) { return 'error:' + String(e); }
})('__MARKER__')
"""


def dismiss_overlay_popup(tab, marker_text: str, wait_after: float = 1.0) -> str:
    """若页面存在含 marker_text 的弹窗则关闭（× 图标 / ESC 兜底）。
    全程 try/except 保护，失败不影响主流程；绝不点击同步/确认按钮。"""
    try:
        r = tab.run_js(JS_DISMISS_POPUP.replace("__MARKER__", marker_text))
        if r in ("clicked", "esc") and wait_after:
            time.sleep(wait_after)
        return r or "none"
    except Exception as e:
        return f"error:{e}"


# ============================================================
# 采集数据统一安全落盘（四个 *_collector.py 共用）
# ============================================================

DATA_DIR = os.path.join(_BACKEND_DIR, "resume_editor", "data")
_KEEP_BACKUPS = 10


def _data_richness(fields: dict):
    """统计采集数据的非空模块数与总内容量，用于空数据拦截判定。

    dict 类型模块若所有子值均为空（如 BOSS 驻外选项的 {"countries": [], ...} 空壳），
    不计为非空模块——否则骨架响应靠空壳 dict 就能凑满拦截阈值。
    """
    def _has_content(d: dict) -> bool:
        for x in d.values():
            if isinstance(x, (list, dict)):
                if len(x):
                    return True
            elif isinstance(x, str):
                if x.strip():
                    return True
            elif x:
                return True
        return False

    non_empty = 0
    total = 0
    for v in fields.values():
        cv = v.get("current_value") if isinstance(v, dict) else v
        if isinstance(cv, dict):
            if cv and _has_content(cv):
                non_empty += 1
                total += len(cv)
        elif isinstance(cv, list):
            if len(cv) > 0:
                non_empty += 1
                total += len(cv)
        elif isinstance(cv, str):
            if cv.strip():
                non_empty += 1
                total += len(cv)
        elif cv:
            non_empty += 1
            total += 1
    return non_empty, total


def backup_json_file(path: str, stem: str, keep: int = _KEEP_BACKUPS) -> str | None:
    """写前备份：把现有 JSON 文件复制到 <同目录>/snapshots/{stem}_{时间戳}.bak.json，只保留最近 keep 份。

    采集落盘（stem={platform}_collect）与 clear-data（stem={platform}_clear）共用同一保险机制，
    误清/误覆盖时不再只能靠 git 或回写快照找回。
    """
    if not os.path.exists(path) or os.path.getsize(path) < 10:
        return None
    snapshot_dir = os.path.join(os.path.dirname(path), "snapshots")
    os.makedirs(snapshot_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    bak_path = os.path.join(snapshot_dir, f"{stem}_{stamp}.bak.json")
    try:
        with open(path, "r", encoding="utf-8") as src, open(bak_path, "w", encoding="utf-8") as dst:
            dst.write(src.read())
    except Exception as e:
        print(f"  [WARN] 备份旧数据失败（继续写入）: {e}")
        return None
    # 清理超出保留数的历史备份
    try:
        olds = sorted(f for f in os.listdir(snapshot_dir) if f.startswith(f"{stem}_") and f.endswith(".bak.json"))
        for old in olds[:-keep]:
            os.remove(os.path.join(snapshot_dir, old))
    except Exception:
        pass
    return bak_path


def _backup_existing(path: str, platform: str) -> str | None:
    """采集落盘备份入口（保留旧名，兼容既有调用）。"""
    return backup_json_file(path, f"{platform}_collect")


# ============================================================
# 回写数据源统一加载与空数据守卫（四个 *_write_back/pusher 共用）
# ============================================================

def data_richness(fields: dict):
    """统计非空模块数与总内容量（公开封装，回写守卫与快照保存校验共用）。"""
    return _data_richness(fields or {})


def ensure_writable_data(platform: str, fields: dict, min_non_empty: int = 3) -> None:
    """回写全局空数据守卫（用户规则 2026-08-30）：非空模块数不足时拒绝回写。

    防止本地数据被清空/接近空时把空内容推上官网覆盖真实资料
    （采集落盘有 min_non_empty 拦截，回写此前完全没有对应闸门）。
    """
    non_empty, total = data_richness(fields)
    if non_empty < min_non_empty:
        raise RuntimeError(
            f"{platform} 本地数据近乎为空（{non_empty} 个非空模块，共 {total} 项），"
            f"已拒绝回写以保护官网在线简历。请先采集或应用映射，确认本地数据完整后重试。"
        )


def load_writeback_source(platform: str, snapshot_path: str, fields_path: str):
    """回写数据源统一加载（快照优先 + 新鲜度检查，用户规则 2026-08-30）。

    返回 (fields, source_path, freshness)。
    freshness.stale = 快照存在且 fields.json 文件更新于快照之后——
    提示用户先重新「保存快照」，避免把旧快照推上官网。
    """
    import datetime as _dt
    freshness = {
        "using_snapshot": False,
        "snapshot_created_at": None,
        "fields_mtime": None,
        "stale": False,
        "warning": None,
    }
    fields_mtime = os.path.getmtime(fields_path) if os.path.exists(fields_path) else None
    if fields_mtime:
        freshness["fields_mtime"] = _dt.datetime.fromtimestamp(fields_mtime).isoformat(timespec="seconds")

    if os.path.exists(snapshot_path):
        freshness["using_snapshot"] = True
        try:
            with open(snapshot_path, encoding="utf-8") as f:
                raw = json.load(f)
            fields = raw.get("fields", {})
            meta_created = (raw.get("meta") or {}).get("created_at")
        except Exception as e:
            raise RuntimeError(f"回写快照损坏（{os.path.basename(snapshot_path)}），请重新「保存快照」: {e}") from e
        freshness["snapshot_created_at"] = meta_created or _dt.datetime.fromtimestamp(
            os.path.getmtime(snapshot_path)
        ).isoformat(timespec="seconds")
        if fields_mtime and os.path.getmtime(snapshot_path) < fields_mtime:
            freshness["stale"] = True
            freshness["warning"] = (
                f"回写快照生成于 {freshness['snapshot_created_at']}，早于本地数据修改时间 "
                f"{freshness['fields_mtime']}；如刚应用映射/编辑，请先点「保存快照」再回写"
            )
        return fields, snapshot_path, freshness

    with open(fields_path, encoding="utf-8") as f:
        return json.load(f), fields_path, freshness


def atomic_write_json(path: str, data) -> None:
    """原子写 JSON：进程唯一临时文件 + os.replace（写一半被杀不留损坏文件）。

    tmp 名带 pid：API 进程与采集/回写子进程、healer 并发写同一文件时，
    不会互相 open+truncate 对方正在写的临时文件。
    """
    tmp_path = f"{path}.tmp.{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def save_fields_json(platform: str, output_path: str, fields: dict, min_non_empty: int = 3) -> None:
    """采集结果统一落盘：空数据拦截 + 写前备份 + 原子替换。

    - 空数据拦截：非空模块数 < min_non_empty 时拒绝写入并抛 RuntimeError，
      防止 hydration 未完成/反爬软拦截采到的空壳覆盖已有好数据；
    - 原子写：临时文件 + os.replace，写一半被杀也不会留下损坏 JSON；
    - 写前备份：覆盖前把现有数据备份到 data/snapshots/{platform}_collect_*.bak.json。

    采集语义 = 镜像官网现状（官网删除的内容同步清空），安全性由拦截+备份保障，
    不再做有"陈旧数据永不清空"缺陷的合并。
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    non_empty, total = _data_richness(fields)
    if non_empty < min_non_empty:
        raise RuntimeError(
            f"采集到的数据近乎为空（{non_empty} 个非空模块，共 {total} 项内容），"
            f"已拒绝写入 {os.path.basename(output_path)} 以保护本地数据。"
            "请确认浏览器中已登录且简历页加载完整后重试。"
        )

    bak = _backup_existing(output_path, platform)
    if bak:
        print(f"  [OK] 已备份旧数据: {os.path.basename(bak)}")

    atomic_write_json(output_path, fields)
    print(f"  [OK] 数据已保存: {output_path}")
    print(f"  [OK] 共 {len(fields)} 个字段（{non_empty} 个非空模块）")
