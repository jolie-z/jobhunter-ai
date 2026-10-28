"""全局 A 级岗位能力画像服务（2026-10-11 重构；2026-10-12 详细核对版）。

存储：画像唯一事实源在本地 job_hunter.db 的 system_reports 表
（key=global_jd_report）；飞书字段为展示镜像（best-effort 写）+ 一次性迁移源。

取样：两级策略（A≥20 纯 A 精选 Top20 / A<20 补 B 至 20——用户 2026-10-12 拍板，
取代三阶段）+ 公司岗位名去重 + 单条 JD 截 4000 字 + 层级标注喂 LLM
（见 jd_report_sampling.py）；输出模板与写前校验在 jd_report_prompts.py
（详细核对版：条目式详描/差异例外/行业分布/散点要求/来源标记〔来源:N〕，
前端据 meta.sample_jobs 渲染可点击岗位深链）。

可靠性：LLM 3 次尝试指数退避（网关异常同权计入）+ 写前校验硬闸 +
生成互斥锁（并发等待期间已有新生成则直接复用）。每日自动重建已按用户
要求移除（省 token）；陈旧提醒（>7 天角标）为纯前端展示。

对外契约（不可破坏，消费方零改动）：get_global_jd_report() -> str | None、
generate_jd_report_service() -> str、update_global_jd_report() -> bool；
HTTP get_jd_report/generate_jd_report 响应统一为 {data, meta}。
"""

import asyncio
import json
import logging
import sqlite3
import sys
import threading
import time
from datetime import datetime

import requests

import common.config as _ccfg
from app.core.config import settings
from app.core.db_bootstrap import resolve_main_db_path
from app.core.feishu_client import feishu_client
from app.core.feishu_utils import get_tenant_access_token
from app.strategy import jd_report_prompts as prompts
from app.strategy import jd_report_sampling as sampling
from common.config import get_openai_client

logger = logging.getLogger("strategy_jd_report")
logger.setLevel(logging.INFO)

_JD_REPORT_KEY = "global_jd_report"
# 取样参数（两级策略：A≥20 纯 A 精选 / A<20 补 B 至 20——用户 2026-10-12 拍板；
# prompt/校验/格式常量在 jd_report_prompts.py）
_MAX_JOBS = 20
_RECENCY_DAYS = 90
# 可靠性参数
_LLM_ATTEMPTS = 3
_LLM_BACKOFF_SECONDS = (2, 4)  # 第 1/2 次重试前的退避（测试可 monkeypatch 归零）
# 陈旧提醒（>7 天亮角标）为纯前端展示（STALE_MS）；自动重建已按用户要求移除（省 token）

_DDL_NOTE = "system_reports 表由 app/core/db_bootstrap.py 启动引导统一建表（勿在此重复维护 DDL）"


def _get_svc():
    return sys.modules.get("app.strategy.service")


def _get_report_db_path() -> str:
    return resolve_main_db_path()


def _get_report_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_report_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------- 本地存储（唯一事实源） ----------

def _save_local_report_sync(value: str, generated_at: str | None, meta: dict) -> None:
    conn = _get_report_conn()
    try:
        conn.execute(
            "INSERT INTO system_reports(key, value, generated_at, meta_json) VALUES(?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, generated_at=excluded.generated_at, "
            "meta_json=excluded.meta_json",
            (_JD_REPORT_KEY, value, generated_at, json.dumps(meta, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def _load_local_report_sync() -> tuple[str | None, dict]:
    """读本地行。墓碑行（value=''，飞书已确认无画像）返回 (None, {"tombstone": True})。"""
    conn = _get_report_conn()
    try:
        row = conn.execute(
            "SELECT value, generated_at, meta_json FROM system_reports WHERE key=?", (_JD_REPORT_KEY,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None, {}
    try:
        meta = json.loads(row["meta_json"] or "{}")
    except (TypeError, ValueError):
        meta = {}
    value = row["value"] or None  # 墓碑 '' 归一为 None
    if value is None:
        meta.setdefault("tombstone", True)
    meta.setdefault("generated_at", row["generated_at"])
    return value, meta


def _has_local_row() -> bool:
    """行存在性探针（CR-R3 注：生产路径已由 _load_local_report_sync 的墓碑标记
    替代，不再有调用方；保留供单元测试断言墓碑落库用）。"""
    conn = _get_report_conn()
    try:
        return conn.execute("SELECT 1 FROM system_reports WHERE key=?", (_JD_REPORT_KEY,)).fetchone() is not None
    finally:
        conn.close()


# ---------- 飞书一次性迁移（两段式，采纳审查 P1-1） ----------

def _feishu_resumes_search_url() -> str:
    return (
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}"
        f"/tables/{settings.FEISHU_TABLE_ID_RESUMES}/records/search"
    )


def _migrate_from_feishu_sync() -> tuple[str | None, dict, bool]:
    """从飞书简历库旧字段迁移画像（仅本地无行时调用一次）。

    两段式防「禁用旧简历的陈旧画像被固化」：先搜「启用 + 画像非空」；
    空则兜底分页拉全「画像非空」，按响应 last_modified_time 取最新一条。
    返回 (value, meta, definitive)：definitive=True 表示飞书明确无画像
    （可写本地墓碑，此后读取不再迁移）；definitive=False 表示迁移过程
    出错（瞬态失败，下次读取应重试）。迁移值 generated_at=NULL（生成时间
    不可考），刷新判定视为超期，最迟次日自动重建。
    """
    svc = _get_svc()
    token_getter = getattr(svc, "get_tenant_access_token", get_tenant_access_token) if svc else get_tenant_access_token
    req = getattr(svc, "requests", requests) if svc else requests
    token = token_getter()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = _feishu_resumes_search_url()
    field = "全局A级JD能力画像"

    def _search(payload: dict) -> dict:
        """单页 search，返回响应 data 部分（含 items/has_more/page_token）。"""
        resp = req.post(url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"飞书返回错误: {data.get('msg')}")
        return data.get("data") or {}

    try:
        enabled = _search({
            "filter": {"conjunction": "and", "conditions": [
                {"field_name": "当前状态", "operator": "is", "value": ["启用"]},
                {"field_name": field, "operator": "isNotEmpty", "value": []},
            ]},
            "page_size": 1,
        })
        chosen = None
        if enabled.get("items"):
            chosen = enabled["items"][0]
        else:
            all_items: list[dict] = []
            page_token = ""
            while True:
                body = {
                    "filter": {"conjunction": "and", "conditions": [
                        {"field_name": field, "operator": "isNotEmpty", "value": []},
                    ]},
                    "page_size": 100,
                }
                if page_token:
                    body["page_token"] = page_token
                data_part = _search(body)
                all_items.extend(data_part.get("items") or [])
                if not data_part.get("has_more"):
                    break
                page_token = data_part.get("page_token") or ""
                if len(all_items) >= 1000:  # 简历库量级护栏
                    break
            if all_items:
                # bitable search 的 sort 不支持系统修改时间，last_modified_time 在
                # 响应 item 上，客户端取 max（兜底路径防「陈旧画像固化」）
                chosen = max(all_items, key=lambda it: it.get("last_modified_time") or 0)
        if not chosen:
            return None, {}, True  # 飞书明确无画像：definitive-empty，可写墓碑
        value = sampling.extract_text((chosen.get("fields") or {}).get(field))
        if not value:
            return None, {}, True
        meta = {"migrated_from_feishu": True, "generated_at": None}
        _save_local_report_sync(value, None, meta)
        logger.info("[jd_report] 已从飞书简历库迁移历史画像到本地 system_reports（generated_at 未知）")
        return value, meta, False
    except Exception as e:
        logger.warning(f"[jd_report] 飞书迁移读取失败（瞬态，下次读取重试）: {e}")
        return None, {}, False


def _load_or_migrate_sync() -> tuple[str | None, dict]:
    """本地优先；无行时一次性迁移。墓碑（飞书明确无画像）永久免迁移。

    墓碑判定复用 _load_local_report_sync 的 meta 标记（tombstone 行返回
    (None, {"tombstone": True})，无行返回 (None, {})），不发第二次 SELECT。
    """
    value, meta = _load_local_report_sync()
    if value:
        return value, meta
    if meta.get("tombstone"):
        return None, {}  # 墓碑行：飞书已确认无画像
    value, meta, definitive = _migrate_from_feishu_sync()
    if value:
        return value, meta
    if definitive:
        # 负缓存落库：空系统不再每次读取都穿透飞书（审查 P1-1）
        _save_local_report_sync("", None, {"tombstone": True})
    return None, {}


# ---------- 进程内缓存（value + meta；uvicorn 单进程无多实例一致性问题） ----------
# 负缓存：瞬态迁移失败时缓存 None 60s，防飞书故障期读取穿透重试（墓碑是持久负缓存，
# 这里只兜瞬态失败；用户主动读 with_meta 不走负缓存，保证 UI 重试可达）
_JD_REPORT_CACHE: dict = {"value": None, "meta": None, "at": 0.0, "neg": False}
_JD_REPORT_TTL_SECONDS = 300.0
_JD_REPORT_NEG_TTL_SECONDS = 60.0
_jd_report_cache_lock = threading.Lock()


def _set_cache(value: str | None, meta: dict) -> None:
    with _jd_report_cache_lock:
        _JD_REPORT_CACHE["value"] = value
        _JD_REPORT_CACHE["meta"] = meta
        _JD_REPORT_CACHE["at"] = time.time()
        _JD_REPORT_CACHE["neg"] = value is None


# ---------- 读取（对外契约：get_global_jd_report 签名不变） ----------

def _get_global_jd_report_sync() -> tuple[str | None, dict]:
    """同步读本地（含一次性迁移）。阻塞 I/O 必须 asyncio.to_thread 卸载——
    曾在 async 端点直连飞书致事件循环卡死（2026-09-23 慢因修复，现读本地后
    仍守此纪律：sqlite/迁移均在 to_thread 内）。"""
    return _load_or_migrate_sync()


async def get_global_jd_report_with_meta() -> tuple[str | None, dict]:
    """读报告 + 元数据（本地直读不经 TTL，sqlite 亚毫秒级）。"""
    return await asyncio.to_thread(_load_or_migrate_sync)


async def get_global_jd_report() -> str | None:
    """读全局画像（进程内缓存 5 分钟 + 负缓存 60 秒 + to_thread 卸载阻塞 I/O）。

    双轨契约（2026-10-12）：返回「附：下游速览」精简版（~2k tokens）供下游 LLM
    消费方注入——详细版 ~1 万字符全量塞入是噪音且烧 token；弹窗/人读走
    get_global_jd_report_with_meta()（返回完整 value）。速览缺失（旧报告/迁移值）
    回退完整版，行为兼容。
    """
    now = time.time()
    with _jd_report_cache_lock:
        if _JD_REPORT_CACHE["value"] is not None and now - _JD_REPORT_CACHE["at"] < _JD_REPORT_TTL_SECONDS:
            return (_JD_REPORT_CACHE["meta"] or {}).get("llm_brief") or _JD_REPORT_CACHE["value"]
        if _JD_REPORT_CACHE["neg"] and now - _JD_REPORT_CACHE["at"] < _JD_REPORT_NEG_TTL_SECONDS:
            return None

    report, meta = await asyncio.to_thread(_load_or_migrate_sync)
    if report:
        _set_cache(report, meta)
        return meta.get("llm_brief") or report
    return None


# ---------- 生成（互斥锁 + 两级取样 + 重试 + 写前校验） ----------

_generate_lock = asyncio.Lock()

# 长报告防截断：显式放宽输出上限；网关拒绝该参数时回退不传（打 WARNING 防静默死循环）
_LLM_MAX_TOKENS = 16384


def _get_llm_client():
    svc = _get_svc()
    getter = getattr(svc, "get_openai_client", get_openai_client) if svc else get_openai_client
    # 画像自带 _LLM_ATTEMPTS 次外层退避重试（异常与质量校验同权计入），SDK 级重试归零：
    # 长报告本就是分钟级任务，SDK 再叠 3 次重试只放大挂死时长（2026-10-13 实测
    # glm-5.3-flash 9 连发 180s 占死生成锁 37 分钟）。无外层循环的交互链路
    # （grill/排版/联动）用 max_retries=1 同族治理，见 grill_service._get_client()。
    try:
        return getter(caller="jd_report", max_retries=0)
    except TypeError:
        return getter()


async def _generate_report_text(llm_client, combined_jd_text: str, a_count: int) -> str:
    system_prompt = prompts.build_system_prompt(a_count)
    model = _ccfg.OPENAI_MODEL if _ccfg.OPENAI_MODEL else "gpt-4o"

    def call_llm(include_max_tokens: bool, disable_thinking: bool) -> str:
        kwargs: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": combined_jd_text},
            ],
            "temperature": 0.3,
        }
        if include_max_tokens:
            kwargs["max_tokens"] = _LLM_MAX_TOKENS
        if disable_thinking:
            # 推理模型的思考计入 completion 预算：聚合 20 条 JD 的长报告任务思考量巨大，
            # 思考先烧尽 16384 预算、正文一字未写即被掐断（finish_reason=length 但
            # content 为空），旧逻辑只读 content → 误报「AI 返回空内容」并确定性重演
            # （2026-10-22 真机工单：三次尝试 completion 全部精准打满上限）。
            # 聚合提炼类确定性任务关思考是常规做法；本地网关实测顶层
            # {"thinking":{"type":"disabled"}} 生效，enable_thinking:false 与
            # reasoning.enabled:false 两个变体实测无效，勿改。
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        response = llm_client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        content = (choice.message.content or "").strip()
        if not content and getattr(choice, "finish_reason", "") == "length":
            # 预算耗尽型截断与真空产出分开归因，终端/弹窗不再出现误导性的「空内容」。
            # 文案严禁出现 max_tokens/thinking 字面——下方重试循环靠这两个子串识别
            # 「网关拒参」做参数降级，预算耗尽命中会把网关没拒过的参数错删掉。
            raise RuntimeError("输出预算被思考/正文耗尽（finish_reason=length 且正文为空），请确认推理模型思考已关闭，或联系维护者调整输出上限")
        return content

    last_reason = ""
    allow_max_tokens = True
    allow_thinking_disable = True
    for attempt in range(1, _LLM_ATTEMPTS + 1):
        try:
            text = await asyncio.to_thread(call_llm, allow_max_tokens, allow_thinking_disable)
        except Exception as e:
            # 网关超时/429/5xx 与内容不合格同权：计入尝试次数并退避重试
            last_reason = f"调用异常: {e}"
            err_lower = str(e).lower()
            if allow_thinking_disable and "thinking" in err_lower:
                # 非 deepseek 系网关可能不认顶层 thinking 参数：降级去掉后重试，
                # 避免为兼容一家网关锁死画像生成（与下方 max_tokens 同款治理）
                allow_thinking_disable = False
                logger.warning(f"[jd_report] 网关不接受 thinking 参数，后续尝试不再携带（推理模型可能因思考耗尽输出预算）: {e}")
            elif allow_max_tokens and "max_tokens" in err_lower:
                allow_max_tokens = False
                logger.warning(f"[jd_report] 网关不接受 max_tokens 参数，后续尝试不再携带（注意模型默认输出上限可能截断长报告）: {e}")
            else:
                logger.warning(f"[jd_report] LLM 调用异常（第 {attempt}/{_LLM_ATTEMPTS} 次）: {e}")
            if attempt < _LLM_ATTEMPTS:
                await asyncio.sleep(_LLM_BACKOFF_SECONDS[attempt - 1])
            continue
        ok, reason = prompts.validate_report(text)
        if ok:
            if attempt > 1:
                logger.info(f"[jd_report] 第 {attempt} 次尝试通过质量校验")
            return text
        last_reason = reason
        logger.warning(f"[jd_report] LLM 产出未过校验（第 {attempt}/{_LLM_ATTEMPTS} 次）: {reason}")
        if attempt < _LLM_ATTEMPTS:
            await asyncio.sleep(_LLM_BACKOFF_SECONDS[attempt - 1])  # 指数退避
    if not allow_max_tokens:
        last_reason += "（网关不支持 max_tokens 参数且回退后仍失败，疑似模型输出上限不足，建议更换模型）"
    raise ValueError(f"AI 生成的报告连续 {_LLM_ATTEMPTS} 次未通过质量校验：{last_reason}")


def _should_reuse_during_wait(captured_generated_at: str | None, current_meta: dict) -> bool:
    """双击/并发幂等：等锁期间他人已完成一次生成（generated_at 变化）→ 直接复用。

    冷启动（captured 为 None）同样生效：只要此刻已有 generated_at，说明是
    等待期间新产生的——否则并发首击会全部穿透到 LLM 重复烧 token。
    """
    current_at = (current_meta or {}).get("generated_at")
    if not current_at:
        return False
    return current_at != captured_generated_at


async def generate_jd_report_service() -> str:
    """生成全局 A 级岗位能力画像（本地落库 + best-effort 飞书镜像），返回报告文本。"""
    captured = await asyncio.to_thread(_load_local_report_sync)
    captured_at = (captured[1] or {}).get("generated_at")

    async with _generate_lock:
        current = await asyncio.to_thread(_load_local_report_sync)
        if _should_reuse_during_wait(captured_at, current[1] if current[0] else {}):
            logger.info("[jd_report] 等待期间已有新生成，直接复用（不重复烧 token）")
            return current[0]

        svc = _get_svc()
        feishu = getattr(svc, "feishu_client", feishu_client) if svc else feishu_client
        token = await feishu.get_tenant_access_token()
        now = datetime.now()

        async def _fetch_b_pool():
            b_items, _ = await sampling.search_job_records(token, "B", sampling.sample_field_names())
            return b_items

        a_items, total_a = await sampling.search_job_records(token, "A", sampling.sample_field_names())
        selection = await sampling.select_samples(
            a_items, total_a,
            max_jobs=_MAX_JOBS, recency_days=_RECENCY_DAYS, now=now,
            b_fetch=_fetch_b_pool,
        )
        if not selection["a_selected"] and not selection["b_selected"]:
            raise ValueError(
                "岗位池为空：飞书岗位表中既无 A 级也无 B 级岗位。"
                "请先在『岗位数据汇总表』中给岗位完成综合评级后再生成画像。"
            )

        combined_jd_text = sampling.build_sample_text(selection)
        logger.info(
            "[jd_report] 取样完成：%d 条 A + %d 条 B（stage=%s，池内 A 总数 %d）",
            len(selection["a_selected"]), len(selection["b_selected"]),
            selection["stage"], total_a,
        )

        report_text = await _generate_report_text(
            _get_llm_client(), combined_jd_text, len(selection["a_selected"])
        )
        # 双轨拆分（2026-10-12 用户采纳）：LLM 在报告末尾同步产出「附：下游速览」，
        # value（详细版）给弹窗/镜像/落库，brief 给下游 LLM 消费方——
        # 详细版 ~1 万字符全量塞进每次下游调用是 10-15k tokens 噪音，速览版 ~2k 足够
        report_value, llm_brief = prompts.split_brief(report_text)

        generated_at = now.strftime("%Y-%m-%dT%H:%M:%S")
        meta = {
            "generated_at": generated_at,
            "a_count": len(selection["a_selected"]),
            "b_count": len(selection["b_selected"]),
            "total_a_in_pool": total_a,
            "a_record_ids": [it.get("record_id") for it in selection["a_selected"]],
            "b_record_ids": [it.get("record_id") for it in selection["b_selected"]],
            "model": _ccfg.OPENAI_MODEL if _ccfg.OPENAI_MODEL else "gpt-4o",
            "stage": selection["stage"],
            # 来源映射：报告里的〔来源:N〕据此渲染成可点击的定制面板深链（/?job_id=record_id）
            "sample_jobs": sampling.build_sample_jobs(selection),
            "format": "detailed_v2",
            "llm_brief": llm_brief,
        }
        await asyncio.to_thread(_save_local_report_sync, report_value, generated_at, meta)
        _set_cache(report_value, meta)

        # 展示镜像：best-effort 写飞书启用简历记录（读已不依赖它；失败不影响事实源）
        mirrored = await update_global_jd_report(report_value)
        if not mirrored:
            logger.warning("[jd_report] 飞书镜像写入失败（本地事实源已落库，不影响使用）")
        return report_value


# ---------- 飞书展示镜像（best-effort；读路径已不依赖） ----------

def _update_global_jd_report_sync(report_text: str) -> bool:
    """镜像写的同步实现（requests 阻塞 I/O，必须经 asyncio.to_thread 调用）。"""
    svc = _get_svc()
    token_getter = getattr(svc, "get_tenant_access_token", get_tenant_access_token) if svc else get_tenant_access_token
    req = getattr(svc, "requests", requests) if svc else requests
    token = token_getter()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    search_url = _feishu_resumes_search_url()
    payload = {
        "filter": {
            "conjunction": "and",
            "conditions": [
                {"field_name": "当前状态", "operator": "is", "value": ["启用"]}
            ],
        },
        "page_size": 1,
    }
    try:
        resp = req.post(search_url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            logger.warning(f"[update_global_jd_report] 搜索启用简历失败: {data.get('msg')}")
            return False
        items = (data.get("data") or {}).get("items") or []
        if not items:
            logger.warning("[update_global_jd_report] 未找到启用的简历记录（镜像跳过，本地事实源不受影响）")
            return False
        record_id = items[0].get("record_id")
        update_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_RESUMES}/records/{record_id}"
        update_resp = req.put(update_url, headers=headers, json={"fields": {"全局A级JD能力画像": report_text}}, timeout=30)
        update_resp.raise_for_status()
        if update_resp.json().get("code") != 0:
            logger.warning(f"[update_global_jd_report] 镜像回写失败: {update_resp.json().get('msg')}")
            return False
        logger.info("[update_global_jd_report] ✅ 能力画像已镜像写飞书简历库")
        return True
    except Exception as e:
        logger.exception(f"[update_global_jd_report] 镜像写异常: {e}")
        return False


async def update_global_jd_report(report_text: str) -> bool:
    """将画像镜像写到飞书简历库「启用简历」记录的『全局A级JD能力画像』字段。

    纯镜像写：失败仅告警（本地事实源已落库）。原实现的刷缓存副作用已剥离
    （缓存由 generate 流程单一刷缓存点管理，避免 value/meta 结构被覆盖）。
    阻塞 requests 经 to_thread 卸载（15s+30s 超时直连事件循环会卡死全站并发）。
    """
    return await asyncio.to_thread(_update_global_jd_report_sync, report_text)
