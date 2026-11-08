"""飞书配置连通性自检（配置页「检测连通性」按钮的后端）。

按依赖顺序逐项检查（除写探针外均为只读探测）：
  credentials   —— App ID/Secret 已填且格式合法（cli_ 前缀）
  token         —— 能换取 tenant_access_token（凭证正确 + 应用已发布）
  bitable       —— App Token 可读（token 正确 + 应用已加为文档协作者）
  tables        —— 各张已配置的数据表 ID 可读
  write_resumes —— 简历库真实写探针（create→delete，验证记录级编辑权限；保存简历的必经链路）
  write_jobs    —— 岗位总表真实写探针（同上；岗位状态回写/结果落表的必经链路）
  chats         —— 机器人所在群列表（机器人能力 + im 权限 + 已拉群的综合体现）
  ws            —— WebSocket 长连接状态

每项返回 {key, label, ok, detail, fix}；fail 时 detail 给出最可能的死因、
fix 给出修复动作。新手排错 90% 的死点：应用未发布版本、应用未加为表格协作者、
协作者只给了「可阅读」（读全绿但写 403，2026-11-03 用户工单）、机器人能力未开、
im 权限未开通、机器人没拉群——诊断文案围绕这些死点组织。
"""
import asyncio
import logging
import time
from datetime import datetime
from typing import Any

import httpx

from common.config import (
    get_configured_value,
    get_missing_llm_keys,
    get_missing_vision_keys,
)

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


def _check(key: str, label: str, ok: bool, detail: str, fix: str = "", optional: bool = False) -> dict[str, Any]:
    return {"key": key, "label": label, "ok": ok, "detail": detail, "fix": fix, "optional": optional}


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


# 写探针记录的标记前缀：残留时可凭此在表里人工识别清理
_PROBE_TAG = "【连通性探针】"


def _explain_write_fail(code: Any, msg: str) -> tuple[str, str]:
    """把记录写入失败翻译成新手能懂的死因 + 修复动作（写探针专用）。

    高级权限特征词判定前置：避免英文报错同时含 "advance" 与 "permission/denied"
    时被 403 分支截获、给错修复指引。"""
    s = str(code)
    low = (msg or "").lower()
    if "space" in low or "advance" in low or "高级权限" in (msg or ""):
        return (
            "多维表格开启了高级权限，应用账号没有该表的编辑角色",
            "多维表格 → 高级权限 → 给应用对应的协作者授予「可编辑」角色",
        )
    if "403" in s or "forbidden" in low or "permission" in low or "denied" in low:
        return (
            "应用对该表没有编辑权限（最常见：文档协作者给的是「可阅读」而不是「可编辑」）",
            "打开多维表格 → 右上角「分享」→ 把应用添加为协作者并选「可编辑」；同时确认权限管理里 bitable 是读写权限（不是 readonly）且已发布版本",
        )
    if "field" in low or "字段" in (msg or ""):
        return (
            f"写入被飞书拒绝（字段问题：{msg or code}）",
            "探针写的是表内真实存在的字段，一般不会走到这里；真实保存写的字段与探针不同，可忽略本项继续使用，反复出现请反馈",
        )
    if "404" in s or "not found" in low or "notfound" in low or "invalid" in low:
        return (
            "找不到目标表或记录容器（Table ID 可能已失效）",
            "重新复制：打开多维表格对应表，地址栏 table= 后的字符串即 Table ID",
        )
    return f"飞书返回错误（code={code}）：{msg}", "确认应用已发布版本、bitable 为读写权限、且文档协作者为「可编辑」"


async def _probe_field_name(client: httpx.AsyncClient, token: str, app_token: str, table_id: str) -> str | None:
    """读取表的真实字段清单，挑首个文本类字段作为探针写入字段。

    探针字段必须真实存在（此前写死「标题」，表里没有该字段时飞书回
    FieldNameNotFound 被误判成写入失败）。找不到文本字段时返回 None，
    由调用方退化为空记录写入（仅验证记录级 create/delete 权限）。
    """
    try:
        resp = await client.get(
            f"{_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
            params={"page_size": 100},
            headers={"Authorization": f"Bearer {token}"},
        )
        data = resp.json()
    except Exception:
        return None
    if data.get("code") != 0:
        return None
    for it in (data.get("data") or {}).get("items") or []:
        # ui_type==Text 是单行文本；类型 1 为多行文本，均接受纯字符串写入
        if it.get("ui_type") == "Text" or it.get("type") == 1:
            name = it.get("field_name") or ""
            if name:
                return name
    return None


async def _probe_table_write(
    client: httpx.AsyncClient, token: str, app_token: str, table_id: str, table_label: str,
) -> tuple[bool, str, str]:
    """对指定表执行 create→delete 写探针。返回 (ok, detail, fix)。

    成功判定以 create 返回 code==0 为准；delete 失败不推翻写入结论，但如实告知残留
    （记录名带 _PROBE_TAG 标记，可人工识别清理）。任何网络异常都按失败收场并提示重试。
    写入字段取表内首个真实存在的文本字段（无文本字段时写空记录），
    避免 FieldNameNotFound 类误报——探针验证的是记录级写权限，不关心字段内容。
    """
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    create_url = f"{_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    field_name = await _probe_field_name(client, token, app_token, table_id)
    probe_fields: dict[str, Any] = {field_name: f"{_PROBE_TAG}JobHunter 连通性探针 {datetime.now().strftime('%m-%d %H:%M:%S')}"} if field_name else {}
    try:
        resp = await client.post(create_url, headers=headers, json={"fields": probe_fields})
        data = resp.json()
    except Exception as e:
        return False, f"写入请求网络失败：{e}", "确认本机可访问 open.feishu.cn（代理/VPN 可能劫持）后重跑检测"

    if data.get("code") != 0:
        detail, fix = _explain_write_fail(data.get("code"), data.get("msg", ""))
        return False, f"{table_label}写入被飞书拒绝：{detail}", fix

    record_id = ((data.get("data") or {}).get("record") or {}).get("record_id") or ""
    if not record_id:
        # create 成功但响应里没带回 record_id：无法自清理，如实告知
        return True, f"{table_label}写入成功（探针记录已写入，但飞书未返回记录 ID，请在表中按「{_PROBE_TAG}」标记手动清理）", ""

    # 立即删除探针记录，验证 delete 权限并保证零残留
    try:
        del_resp = await client.delete(f"{create_url}/{record_id}", headers=headers)
        del_data = del_resp.json()
        if del_data.get("code") != 0:
            return True, (f"{table_label}写入成功（探针记录删除被拒：{del_data.get('msg', '')}；"
                          f"请在表中按「{_PROBE_TAG}」标记手动清理该条探针记录）"), ""
    except Exception as del_e:
        return True, (f"{table_label}写入成功（探针记录删除请求异常：{del_e}；"
                      f"请在表中按「{_PROBE_TAG}」标记手动清理该条探针记录）"), ""
    return True, f"{table_label}写入与删除均成功（记录级编辑权限正常）", ""


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

        # ---- 4.5 写探针：真实写一次再删（简历库 + 岗位总表，保存简历/岗位回写的必经权限链）----
        # 读接口全通 ≠ 记录可写：多维表格协作者权限分「可阅读/可编辑」两级，scope 也分
        # readonly 与读写——此前只测读，用户会把文档权限给成「可阅读」导致全绿但保存 403。
        # 用真实 create→delete 验证 create 与 delete 两段权限；记录带探针标记便于人工识别残留。
        if token and app_token:
            probe_specs = [
                ("write_resumes", "简历库", "FEISHU_TABLE_ID_RESUMES"),
                ("write_jobs", "岗位总表", "FEISHU_TABLE_ID_JOBS"),
            ]
            for probe_key, table_label, table_cfg_key in probe_specs:
                table_id = _cfg_val(table_cfg_key)
                if not table_id:
                    checks.append(_check(
                        probe_key, f"{table_label}可写（记录级编辑权限）", False,
                        f"尚未配置 {table_label} 的 Table ID",
                        f"在「飞书」分组填入 {table_label} 的 Table ID（多维表格地址栏 table= 后的字符串）"))
                    continue
                probe_ok, probe_detail, probe_fix = await _probe_table_write(
                    client, token, app_token, table_id, table_label)
                checks.append(_check(probe_key, f"{table_label}可写（记录级编辑权限）",
                                     probe_ok, probe_detail, probe_fix))

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


# ============================================================
# LLM 通道诊断（配置页「LLM 大模型」分组的「测试连通性」按钮后端）
# ============================================================

# 探活用的极小请求文案与 1×1 测试图（PNG，透明单像素）
_PING_TEXT = "请只回复两个字母：OK"
_TINY_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

# 诊断专用短超时：探活不该被 get_safe_httpx_client 的 LLM 长超时（默认 360s，可配置）拖住
_DIAGNOSE_TIMEOUT_SECONDS = 30.0


def _explain_llm_fail(e: Exception) -> tuple[str, str]:
    """把 OpenAI 兼容调用异常翻译成新手能懂的死因 + 修复动作。"""
    import openai

    msg = str(e)
    low = msg.lower()
    if isinstance(e, openai.AuthenticationError) or "401" in low or "invalid api key" in low:
        return (
            "API Key 无效或已过期（服务端返回 401）",
            "核对 Key 是否复制完整（首尾别带空格）、账户是否有余额/免费额度是否用尽",
        )
    if isinstance(e, openai.NotFoundError):
        if "model" in low:
            return (
                f"模型名不存在（404）：{msg[:120]}",
                "核对「推理模型」名是否为该服务商的可用模型名；Base URL 与模型必须同一家服务商",
            )
        return (
            "接口路径不存在（404）：Base URL 多半填错了",
            "确认 Base URL 以 /v1 结尾、域名拼写正确（如 https://api.deepseek.com/v1）",
        )
    if isinstance(e, openai.RateLimitError) or "429" in low:
        return (
            "触发限流或额度不足（429）",
            "去服务商控制台检查额度与限流配置，稍后重试",
        )
    if isinstance(e, openai.APITimeoutError) or "timed out" in low or "timeout" in low:
        return (
            "请求超时：本机到服务商之间网络不通",
            "检查代理/VPN 干扰（系统已强制直连不走代理）；确认服务商服务状态页正常",
        )
    if isinstance(e, openai.APIConnectionError):
        return (
            "无法建立连接：域名解析失败或网络被拦截",
            "核对 Base URL 域名拼写；在本机浏览器打开 Base URL 确认可达",
        )
    if isinstance(e, openai.BadRequestError):
        return (
            f"服务端拒绝请求（400）：{msg[:140]}",
            "常见原因：模型名与能力不匹配（如非视觉模型收图）、网关不支持某参数；核对模型名后重试",
        )
    return (
        f"服务端返回错误：{msg[:160]}",
        "把该报错与服务商文档对照排查；确认无误仍失败欢迎提 issue",
    )


def _short_client(api_key: str, base_url: str | None):
    """诊断专用 OpenAI 客户端：30s 超时 + 1 次重试，快速失败。"""
    from openai import OpenAI

    return OpenAI(
        api_key=api_key,
        base_url=base_url or None,
        http_client=httpx.Client(trust_env=False, timeout=_DIAGNOSE_TIMEOUT_SECONDS),
        max_retries=1,
    )


async def diagnose_llm() -> dict[str, Any]:
    """LLM 链路自检：配置齐全性 → 推理通道真实探活 → 视觉通道真实探活。

    视觉为选填能力：未配置时标记 optional=True 不计入 all_ok，
    但 detail 明确列出受影响功能，引导用户按需补配。
    """
    checks: list[dict[str, Any]] = []

    # ---- 1. 推理通道配置齐全性 ----
    missing_llm = get_missing_llm_keys()
    if missing_llm:
        checks.append(_check(
            "main_credentials", "推理通道配置齐全（API Key / Base URL / 推理模型）", False,
            f"缺少：{'、'.join(missing_llm)}",
            "在「LLM 大模型」分组补齐对应字段后保存",
        ))
    else:
        checks.append(_check(
            "main_credentials", "推理通道配置齐全（API Key / Base URL / 推理模型）", True,
            f"API Key 已填写（{_mask(get_configured_value('OPENAI_API_KEY'))}），"
            f"模型 {get_configured_value('OPENAI_MODEL')}",
        ))

        # ---- 2. 推理链路真实探活（一次极小调用，成本可忽略）----
        t0 = time.monotonic()
        client = _short_client(get_configured_value("OPENAI_API_KEY"), get_configured_value("OPENAI_BASE_URL"))
        try:
            model = get_configured_value("OPENAI_MODEL")

            def _ping():
                return client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": _PING_TEXT}],
                    max_tokens=16,
                    temperature=0,
                )

            await asyncio.to_thread(_ping)
            dt = time.monotonic() - t0
            checks.append(_check(
                "main_chat", "推理链路实测（真实调用一次）", True,
                f"模型 {model} 通畅，耗时 {dt:.1f}s。之后调用大模型再报错，可直接回到这里复测定位",
            ))
        except Exception as e:
            detail, fix = _explain_llm_fail(e)
            checks.append(_check("main_chat", "推理链路实测（真实调用一次）", False, detail, fix))
        finally:
            client.close()

    # ---- 3. 视觉通道（选填）----
    missing_vision = get_missing_vision_keys()
    if missing_vision:
        checks.append(_check(
            "vision", "视觉模型（选填：截图识别能力）", False,
            f"未配置：{'、'.join(missing_vision)}。受影响功能：极速录入截图识别、小红书图文清洗、飞书群里发截图录入岗位",
            "在「视觉通道」组的「视觉模型」填入支持图片的模型名（如 mimo-v2.5、gpt-4o）；"
            "Key 与 Base URL 留空则复用主 LLM 通道，主通道不支持图片输入时再单独填写",
            optional=True,
        ))
    else:
        t0 = time.monotonic()
        vision_key = get_configured_value("VISION_API_KEY") or get_configured_value("OPENAI_API_KEY")
        vision_url = get_configured_value("VISION_BASE_URL") or get_configured_value("OPENAI_BASE_URL")
        client = _short_client(vision_key, vision_url)
        try:
            model = get_configured_value("VISION_MODEL")

            def _vision_ping():
                return client.chat.completions.create(
                    model=model,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": _TINY_PNG_DATA_URL}},
                            {"type": "text", "text": "这是一张测试图，能收到请只回复：OK"},
                        ],
                    }],
                    max_tokens=16,
                    temperature=0,
                )

            await asyncio.to_thread(_vision_ping)
            dt = time.monotonic() - t0
            checks.append(_check(
                "vision", "视觉通道实测（发一张测试图）", True,
                f"视觉模型 {model} 可正常读图，耗时 {dt:.1f}s",
            ))
        except Exception as e:
            detail, fix = _explain_llm_fail(e)
            checks.append(_check("vision", "视觉通道实测（发一张测试图）", False, detail, fix))
        finally:
            client.close()

    all_ok = all(c["ok"] for c in checks if not c.get("optional"))
    try:
        from app.core.llm_gate import get_llm_gate
        gate_stats = get_llm_gate().stats()
    except Exception:
        gate_stats = None

    return {
        "code": 0,
        "data": {
            "all_ok": all_ok,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "checks": checks,
            "gate_stats": gate_stats,
        },
    }
