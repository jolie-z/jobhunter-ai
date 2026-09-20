"""飞书配置连通性自检（配置页「检测连通性」按钮的后端）。

只读探测，不写任何数据。按依赖顺序逐项检查：
  credentials —— App ID/Secret 已填且格式合法（cli_ 前缀）
  token       —— 能换取 tenant_access_token（凭证正确 + 应用已发布）
  bitable     —— App Token 可读（token 正确 + 应用已加为文档协作者）
  tables      —— 各张已配置的数据表 ID 可读
  chats       —— 机器人所在群列表（机器人能力 + im 权限 + 已拉群的综合体现）
  ws          —— WebSocket 长连接状态

每项返回 {key, label, ok, detail, fix}；fail 时 detail 给出最可能的死因、
fix 给出修复动作。新手排错 90% 的死点：应用未发布版本、应用未加为表格协作者、
机器人能力未开、im 权限未开通、机器人没拉群——诊断文案围绕这些死点组织。
"""
import logging
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0)
_BASE = "https://open.feishu.cn/open-apis"

# 飞书「飞书」分组里配置的全部表 ID 键（与 app/settings/service.py CONFIG_GROUPS 对应）
# 注：偏好表已废弃（偏好数据走本地 SQLite），不再检查
_TABLE_KEYS = [
    ("FEISHU_TABLE_ID_JOBS", "岗位总表"),
    ("FEISHU_TABLE_ID_RESUMES", "简历库"),
    ("FEISHU_TABLE_ID_INTERVIEW_REPORTS", "面试报告"),
    ("FEISHU_TABLE_ID_INTERVIEW_SUMMARY", "面试汇总"),
    ("FEISHU_TABLE_ID_INTERVIEW_REAL", "真题库"),
]

_OPEN_PLATFORM_BASE = "https://open.feishu.cn/app"


def _cfg_val(key: str) -> str:
    from common.config import _cfg
    return (_cfg(key, json_key=key) or "").strip()


def _mask(val: str) -> str:
    if not val:
        return ""
    return val[:4] + "****" + val[-4:] if len(val) > 8 else "****"


def _check(key: str, label: str, ok: bool, detail: str, fix: str = "") -> dict[str, Any]:
    return {"key": key, "label": label, "ok": ok, "detail": detail, "fix": fix}


def _explain_token_fail(msg: str) -> tuple[str, str]:
    """把 tenant_access_token 接口的错误翻译成新手能懂的死因 + 修复动作。"""
    low = (msg or "").lower()
    if "app_id" in low or "app id" in low:
        return "飞书说 App ID 不存在：App ID 填错，或应用已被删除/停用", "去开放平台「开发者后台」核对 App ID（cli_ 开头）后重新填写"
    if "secret" in low:
        return "App Secret 不正确", "去应用「凭证与基础信息」页重新复制 App Secret，注意不要带上空格"
    if "not exist" in low or "not_exist" in low:
        return "应用不存在：App ID 填错，或应用已被删除", "去 open.feishu.cn 开发者后台确认应用还存在，并核对 App ID"
    if "release" in low or "publish" in low or "version" in low:
        return "应用尚未发布版本（凭证正确但应用不可用）", "在开放平台「版本管理与发布」里创建版本并发布，发布后重试"
    return f"飞书返回错误：{msg}", "检查 App ID / App Secret 是否正确、应用是否已发布版本"


def _explain_bitable_fail(code: Any, msg: str) -> tuple[str, str]:
    low = (msg or "").lower()
    s = str(code)
    if "404" in s or "not found" in low or "notfound" in low or "invalid" in low:
        return "App Token 不对：飞书找不到这个多维表格文档", "重新复制：打开多维表格文档，浏览器地址栏 /base/ 后面那串就是 App Token"
    if "403" in s or "forbidden" in low or "permission" in low or "denied" in low:
        return "应用没有这个文档的权限：最常见原因是应用未被加为文档协作者", "打开多维表格 → 右上角「分享」→ 把应用添加为协作者（可编辑）；同时确认权限管理里已开通 bitable 读写权限并发布版本"
    return f"飞书返回错误（code={code}）：{msg}", "确认应用已发布版本、已开通 bitable 权限、并已加为文档协作者"


def _explain_chats_fail(code: Any, msg: str) -> tuple[str, str]:
    low = (msg or "").lower()
    if "403" in str(code) or "permission" in low or "forbidden" in low or "denied" in low:
        return (
            f"缺 IM 相关权限（飞书原文：{msg or code}）。列出群聊需要 im:chat（获取群组信息），"
            "收发消息需要 im:message；也可能是机器人能力未开通",
            "开放平台 →「添加应用能力」勾选机器人；「权限管理」分别开通 im:message 与 im:chat 读写权限；然后创建版本并发布",
        )
    return f"飞书返回错误（code={code}）：{msg}", "确认已开通机器人能力、im 相关权限且应用已发布版本"


async def diagnose_feishu() -> dict[str, Any]:
    """执行全链路自检，返回结构化诊断结果（绝不返回任何密钥明文）。"""
    checks: list[dict[str, Any]] = []
    chats: list[dict[str, str]] = []

    app_id = _cfg_val("FEISHU_APP_ID")
    app_secret = _cfg_val("FEISHU_APP_SECRET")
    app_token = _cfg_val("FEISHU_APP_TOKEN")

    # ---- 1. 凭证格式 ----
    if not app_id or not app_secret:
        checks.append(_check(
            "credentials", "App ID / App Secret 已填写", False,
            "尚未填写 App ID 或 App Secret",
            "在上方「飞书」分组填写（App ID 以 cli_ 开头，来自开放平台「凭证与基础信息」页）",
        ))
    elif not app_id.startswith("cli"):
        checks.append(_check(
            "credentials", "App ID / App Secret 已填写", False,
            f"App ID 格式不像飞书应用 ID（应为 cli_ 开头，当前 {_mask(app_id)}）",
            "去开放平台「凭证与基础信息」页重新复制 App ID",
        ))
    else:
        checks.append(_check(
            "credentials", "App ID / App Secret 已填写", True,
            f"已填写（{_mask(app_id)}）",
        ))

    token = ""
    async with httpx.AsyncClient(timeout=_TIMEOUT, trust_env=False) as client:
        # ---- 2. 换取 token（凭证有效性 + 应用已发布）----
        if app_id and app_secret:
            try:
                resp = await client.post(
                    f"{_BASE}/auth/v3/tenant_access_token/internal",
                    json={"app_id": app_id, "app_secret": app_secret},
                )
                data = resp.json()
                if data.get("code") == 0:
                    token = data.get("tenant_access_token", "")
                    checks.append(_check("token", "凭证有效（换取到访问令牌）", True, "App ID / Secret 正确，应用可用"))
                else:
                    detail, fix = _explain_token_fail(data.get("msg", ""))
                    checks.append(_check("token", "凭证有效（换取到访问令牌）", False, detail, fix))
            except Exception as e:
                checks.append(_check("token", "凭证有效（换取到访问令牌）", False,
                                     f"网络请求失败：{e}", "确认本机可访问 open.feishu.cn（代理/VPN 可能劫持）"))

        # ---- 3. App Token（bitable 文档可读）----
        if token and app_token:
            try:
                resp = await client.get(
                    f"{_BASE}/bitable/v1/apps/{app_token}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                data = resp.json()
                if data.get("code") == 0:
                    checks.append(_check("bitable", "多维表格文档可读（App Token 正确且已加协作者）", True, "App Token 有效"))
                else:
                    detail, fix = _explain_bitable_fail(data.get("code"), data.get("msg", ""))
                    checks.append(_check("bitable", "多维表格文档可读（App Token 正确且已加协作者）", False, detail, fix))
            except Exception as e:
                checks.append(_check("bitable", "多维表格文档可读（App Token 正确且已加协作者）", False,
                                     f"网络请求失败：{e}", ""))
        elif token and not app_token:
            checks.append(_check("bitable", "多维表格文档可读（App Token 正确且已加协作者）", False,
                                 "尚未填写 App Token", "打开多维表格文档，地址栏 /base/ 后的字符串即 App Token，填入「飞书」分组"))

        # ---- 4. 各数据表 ID（一次拉取文档全部表，再逐个核对，避免单表端点兼容性问题）----
        if token and app_token:
            table_results: list[str] = []
            table_ok = True
            any_configured = False
            valid_ids: set | None = None
            list_err = ""
            try:
                resp = await client.get(
                    f"{_BASE}/bitable/v1/apps/{app_token}/tables",
                    params={"page_size": 100},
                    headers={"Authorization": f"Bearer {token}"},
                )
                data = resp.json()
                if data.get("code") == 0:
                    valid_ids = {
                        it.get("table_id", "")
                        for it in (data.get("data") or {}).get("items") or []
                    }
                else:
                    list_err = data.get("msg", "读取表清单失败")
            except Exception as e:
                list_err = str(e)

            for key, label in _TABLE_KEYS:
                tid = _cfg_val(key)
                if not tid:
                    continue
                any_configured = True
                if valid_ids is None:
                    table_ok = False
                    table_results.append(f"✗ {label}（表清单读取失败：{list_err}）")
                elif tid in valid_ids:
                    table_results.append(f"✓ {label}")
                else:
                    table_ok = False
                    table_results.append(f"✗ {label}（文档里不存在该 Table ID）")
            if not any_configured:
                checks.append(_check("tables", "数据表 ID 已配置且可读", False,
                                     "尚未填写任何数据表 Table ID",
                                     "在多维表格里切换到各张表，地址栏 table= 后的字符串逐张复制填入"))
            else:
                ok_msg = "；".join(table_results)
                if table_ok:
                    checks.append(_check("tables", "数据表 ID 已配置且可读", True, ok_msg))
                else:
                    checks.append(_check("tables", "数据表 ID 已配置且可读", False, ok_msg,
                                         "标 ✗ 的表：重新到多维表格对应表，复制地址栏 table= 后的字符串"))

        # ---- 5. 机器人所在群（机器人能力 + im 权限 + 拉群的综合体现）----
        if token:
            try:
                resp = await client.get(
                    f"{_BASE}/im/v1/chats",
                    params={"page_size": 50},
                    headers={"Authorization": f"Bearer {token}"},
                )
                data = resp.json()
                if data.get("code") == 0:
                    items = (data.get("data") or {}).get("items") or []
                    chats = [
                        {"chat_id": it.get("chat_id", ""), "name": it.get("name") or "未命名群"}
                        for it in items
                    ]
                    if chats:
                        names = "、".join(c["name"] for c in chats[:5]) + ("…" if len(chats) > 5 else "")
                        checks.append(_check("chats", "机器人能力与 IM 权限正常（已在群里）", True,
                                             f"机器人已在 {len(chats)} 个群：{names}"))
                    else:
                        checks.append(_check("chats", "机器人能力与 IM 权限正常（已在群里）", True,
                                             "接口通了，但机器人还没被拉入任何群",
                                             "打开目标飞书群 → 设置 → 群机器人 → 添加你的应用"))
                else:
                    detail, fix = _explain_chats_fail(data.get("code"), data.get("msg", ""))
                    checks.append(_check("chats", "机器人能力与 IM 权限正常（已在群里）", False, detail, fix))
            except Exception as e:
                checks.append(_check("chats", "机器人能力与 IM 权限正常（已在群里）", False,
                                     f"网络请求失败：{e}", ""))

    # ---- 6. WebSocket 长连接状态 ----
    try:
        from app.core.feishu_ws import is_ws_running
        ws_running = is_ws_running()
    except Exception:
        ws_running = False
    if ws_running:
        checks.append(_check("ws", "WebSocket 长连接在线", True,
                             "后端已连接飞书服务器，可以收发消息（试试在群里发 ping）"))
    else:
        has_cred = bool(app_id and app_secret)
        checks.append(_check(
            "ws", "WebSocket 长连接在线", False,
            "长连接未建立" + ("（凭证已填写：若刚保存过配置，重启后端或重新保存一次触发重连；"
                              "也可能尚未切换「长连接」订阅方式）" if has_cred else "（凭证未填写）"),
            "确认事件订阅方式为「使用长连接接收事件」且后端服务在运行；保存一次飞书凭证可触发自动重连",
        ))

    all_ok = all(c["ok"] for c in checks)
    return {
        "code": 0,
        "data": {
            "all_ok": all_ok,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "ws_running": ws_running,
            "chats_count": len(chats),
            "chats": chats,
            "checks": checks,
        },
    }
