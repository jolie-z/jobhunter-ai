"""
飞书聊天框岗位极速录入（图片消息通道）。

webhook 与 WS 长连接共用的入口：用户在聊天框直接发岗位 JD 截图，
机器人在聚合窗口内攒齐多张分屏截图后一次性走 Vision 解析，
复用极速录入服务（app.jobs.service）建岗并回执解析摘要。

暂不支持的消息类型（音频/文件等）统一给友好提示，不再静默丢弃。
"""

import asyncio
import base64
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

from app.core.config import BASE_DIR, settings
from app.core.feishu_messaging import (
    download_message_image,
    send_feishu_card,
    send_feishu_message,
)

logger = logging.getLogger(__name__)

# 多图聚合窗口（秒）：分屏截图往往连发多条消息，窗口内合并为一次 Vision 解析，避免重复建岗
_AGGREGATION_WINDOW_SECONDS = 5.0

# chat_id -> {"items": [(message_id, image_key), ...], "task": asyncio.Task | None}
_pending_images: dict[str, dict] = {}
_ACK_TASKS = set()

# 跨消息会话状态（落盘持久化：只放内存的话，后端一重启反问就失效）
_PENDING_LINKS_PATH = Path(BASE_DIR) / "data" / "pending_job_links.json"
_PENDING_PIPELINE_PATH = Path(BASE_DIR) / "data" / "pending_pipeline_confirm.json"
_LINK_TTL_SECONDS = 24 * 3600


class _PendingStore(dict):
    """chat_id -> record_id 的会话状态存储（落盘持久化，重启可恢复，读取时按 TTL 过滤失效项）。

    加固（2026-09 P2）：落盘改「临时文件 + os.replace」原子替换——旧实现整文件覆写，
    WS 线程与主循环并发写或进程中途被杀会把 JSON 写撕裂，下次加载整文件静默清零；
    内存读写加锁（WS 线程与事件循环两条道并发）；TTL 在每次读取时生效（旧实现只在
    进程启动加载时过滤，长期运行的残留状态永不淘汰，导致「已投递」等旧指针被反复消费）。
    """

    def __init__(self, path: Path, ttl_seconds: int):
        super().__init__()
        self._path = Path(path)
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._ts: dict[str, float] = {}  # key -> 最近写入时间戳（读路径 TTL 判定用）
        self._load()

    def _load(self) -> None:
        try:
            if not self._path.exists():
                return
            raw = json.loads(self._path.read_text())
            now = time.time()
            fresh = {}
            for chat_id, entry in raw.items():
                ts = float(entry.get("ts", 0))
                if now - ts < self._ttl:
                    fresh[str(chat_id)] = str(entry.get("record_id", ""))
                    self._ts[str(chat_id)] = ts
            with self._lock:
                super().clear()
                super().update(fresh)
            if fresh:
                logger.info(f"[聊天录入] 从磁盘恢复会话状态 {len(fresh)} 条（{self._path.name}）")
        except Exception as e:
            logger.warning(f"[聊天录入] 会话状态加载失败（忽略）: {e}")

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            now = time.time()
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(
                {cid: {"record_id": v, "ts": now} for cid, v in self.items()},
                ensure_ascii=False,
            ))
            tmp.replace(self._path)  # 原子替换：不存在写一半的中间态
        except Exception as e:
            logger.warning(f"[聊天录入] 会话状态保存失败（忽略）: {e}")

    def _purge_if_expired(self, key) -> None:
        """读取路径的 TTL 淘汰（调用方须已持锁）：长期运行时残留状态永不堆积。"""
        ts = self._ts.get(key)
        if ts is not None and time.time() - ts >= self._ttl:
            super().pop(key, None)
            self._ts.pop(key, None)

    def __contains__(self, key) -> bool:
        with self._lock:
            self._purge_if_expired(key)
            return super().__contains__(key)

    def get(self, key, default=None):
        with self._lock:
            self._purge_if_expired(key)
            return super().get(key, default)

    def __setitem__(self, key, value) -> None:
        with self._lock:
            super().__setitem__(key, str(value))
            self._ts[key] = time.time()
            self._save()

    def pop(self, key, *default):
        with self._lock:
            self._ts.pop(key, None)
            result = super().pop(key, *default)
            self._save()
            return result

    def clear(self) -> None:
        with self._lock:
            super().clear()
            self._ts.clear()
            self._save()


_pending_job_links = _PendingStore(_PENDING_LINKS_PATH, _LINK_TTL_SECONDS)
_pending_pipeline = _PendingStore(_PENDING_PIPELINE_PATH, _LINK_TTL_SECONDS)


def _set_pending_link(chat_id: str, record_id: str) -> None:
    _pending_job_links[chat_id] = record_id


def _pop_pending_link(chat_id: str) -> str | None:
    if chat_id in _pending_job_links:
        return _pending_job_links.pop(chat_id)
    return None


def _load_pending_links() -> None:
    _pending_job_links._load()


_URL_PATTERN = re.compile(r'https?://\S+')
_SKIP_LINK_WORDS = ("跳过", "skip", "不用了", "没有")

def extract_post_text(content_str: str) -> str:
    """飞书富文本（post 类型）正文提取：遍历段落/元素拼接纯文本。

    飞书对含换行或格式的文本以 post 类型发送（纯文本才是 text 类型），
    多行修改指令/多段文字都会落入此类型，必须提取后走文本管道。
    """
    try:
        post = json.loads(content_str or "{}")
    except (json.JSONDecodeError, TypeError):
        return ""
    parts: list[str] = []
    for paragraph in post.get("content", []) or []:
        if not isinstance(paragraph, list):
            continue
        for el in paragraph:
            if not isinstance(el, dict):
                continue
            if el.get("tag") in ("text", "a"):
                parts.append(str(el.get("text") or el.get("href") or ""))
    return "\n".join(p for p in parts if p)


_UNSUPPORTED_HINT = (
    "🤖 这条消息类型我暂时读不了（目前支持：岗位截图 / 文字）。\n"
    "发岗位 JD 截图或直接粘贴 JD 文字，我可以帮你解析录入～"
)


async def handle_image_message(chat_id: str, image_key: str, message_id: str = "") -> None:
    """飞书图片消息入口：立即首响 + 加入聚合窗口，窗口静默期过后统一解析录入。"""
    logger.info(f"[聊天录入] 收到图片消息 | chat_id={chat_id} | image_key={image_key}")
    entry = _pending_images.setdefault(chat_id, {"items": [], "task": None})
    is_new_batch = not entry["items"]
    entry["items"].append((message_id, image_key))
    if entry["task"] and not entry["task"].done():
        entry["task"].cancel()
    entry["task"] = asyncio.create_task(_flush_after_window(chat_id))
    if is_new_batch:
        # 首响要快（1~2 秒内），否则用户以为卡死会重复发送
        ack = asyncio.create_task(send_feishu_message(
            chat_id,
            f"🖼️ 已收到截图！约 {int(_AGGREGATION_WINDOW_SECONDS)} 秒后开始识别，剩余分屏截图请尽快补发～",
            "chat_id",
        ))
        _ACK_TASKS.add(ack)
        ack.add_done_callback(_ACK_TASKS.discard)


def _bitable_record_url(record_id: str) -> str:
    """多维表格单条记录详情链接（手机点开即该岗位行卡片，方便复核 AI 录入字段）。"""
    app_token = settings.FEISHU_APP_TOKEN or ""
    table_id = settings.FEISHU_TABLE_ID_JOBS or ""
    if not (app_token and table_id and record_id):
        return ""
    return f"https://feishu.cn/base/{app_token}?table={table_id}&record={record_id}"


def build_job_import_card(data: dict[str, Any]) -> dict[str, Any]:
    """录入成功回执卡片：字段摘要 + 「复核多维表格详情」跳转按钮。"""
    from app.jobs.service import _IMPORT_SUMMARY_FIELDS

    md_lines = []
    for key, label in _IMPORT_SUMMARY_FIELDS:
        val = str(data.get(key) or "").strip()
        if val and val not in ("未知", "-"):
            md_lines.append(f"**{label}**：{val}")
    status = str(data.get("跟进状态") or data.get("status") or "新线索").strip()
    md_lines.append(f"**跟进状态**：{status}")

    elements: list[dict[str, Any]] = [{
        "tag": "div",
        "text": {"tag": "lark_md", "content": "\n".join(md_lines)},
    }]

    record_url = _bitable_record_url(str(data.get("record_id") or ""))
    if record_url:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "action",
            "actions": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": "👉 点此复核多维表格岗位详情"},
                "type": "primary",
                "url": record_url,
            }],
        })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "green",
            "title": {"tag": "plain_text", "content": "✅ 岗位截图识别录入成功"},
        },
        "elements": elements,
    }


# 正在识别建岗的 chat_id 集合：识别要几十秒，期间新截图必须等它完成后并入同一批次，
# 否则会另开批次重复识别、同一岗位在表里建多条记录
_importing: set = set()


async def _flush_after_window(chat_id: str) -> None:
    try:
        await asyncio.sleep(_AGGREGATION_WINDOW_SECONDS)
    except asyncio.CancelledError:
        return  # 窗口内又有新图到达，由新的 flush 任务接管
    # 上一批仍在识别：等它跑完再统一导入（等待期间新图持续并入本批次）
    while chat_id in _importing:
        await asyncio.sleep(0.5)
    entry = _pending_images.pop(chat_id, None)
    if not entry or not entry["items"]:
        return
    _importing.add(chat_id)
    try:
        await _import_images(chat_id, entry["items"])
    finally:
        _importing.discard(chat_id)


def _guess_image_mime(raw: bytes) -> str:
    """按魔数判断图片真实类型，避免 data URL 的 Content-Type 标错导致 Vision 模型拒收。"""
    if raw.startswith(b"\x89PNG"):
        return "image/png"
    if raw.startswith(b"GIF8"):
        return "image/gif"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


async def _import_images(chat_id: str, items: list[tuple[str, str]]) -> None:
    """下载消息图片 → base64 → 极速录入 Vision 解析建岗 → 回执摘要。"""
    logger.info(f"[聊天录入] 聚合窗口关闭，开始解析 {len(items)} 张截图 | chat_id={chat_id}")

    images_base64: list[str] = []
    first_error = ""
    for message_id, file_key in items:
        try:
            raw = await download_message_image(message_id, file_key)
            mime = _guess_image_mime(raw)
            images_base64.append(f"data:{mime};base64,{base64.b64encode(raw).decode()}")
        except Exception as e:
            first_error = first_error or str(e)
            logger.warning(f"[聊天录入] 图片下载失败 message_id={message_id} file_key={file_key}: {e}")

    if not images_base64:
        await send_feishu_message(
            chat_id,
            f"❌ 截图下载失败（{first_error[:120]}），请重新发送一次。",
            "chat_id",
        )
        return

    # 视觉前置闸门：未配置视觉模型时无法识别截图，直接回复配置指引（不进解析管道）
    from common.config import get_missing_vision_keys, missing_guide_text
    missing_vision = get_missing_vision_keys()
    if missing_vision:
        await send_feishu_message(
            chat_id,
            "❌ 暂时无法识别截图：" + missing_guide_text(missing_vision, "截图识别")
            + "。填写「视觉模型」后，再重新发送截图即可。",
            "chat_id",
        )
        return

    await send_feishu_message(
        chat_id,
        f"🖼️ 收到 {len(images_base64)} 张截图，正在识别岗位信息，请稍候…",
        "chat_id",
    )

    try:
        from app.jobs.service import (
            DuplicateJobError,
            InvalidJobFieldsError,
            format_job_import_summary,
            import_job_from_images_service,
        )

        data = await import_job_from_images_service(images_base64)
        record_id = str(data.get("record_id") or "")
        logger.info(f"[聊天录入] 解析录入成功 | chat_id={chat_id} | record_id={record_id}")
        # 卡片失败先幂等重试再降级纯文本（统一 helper，防超时双发；文本里 URL 自动识别为链接）
        from app.core.feishu_messaging import send_feishu_card_with_fallback
        await send_feishu_card_with_fallback(chat_id, build_job_import_card(data),
                                             fallback_text=format_job_import_summary(data))

        # 录入后续反问：链接补录（文字）+ 评估这个岗位（按钮卡片，主交互；文字触发作兜底）
        if record_id:
            if not data.get("岗位链接"):
                _set_pending_link(chat_id, record_id)
            _pending_pipeline[chat_id] = record_id
            await send_feishu_message(
                chat_id,
                "没有识别到岗位链接，方便的话把该岗位的网页链接直接发我（回复链接即可自动补录到该岗位）；暂无链接回复「跳过」。",
                "chat_id",
            )
            try:
                await send_feishu_card(chat_id, build_pipeline_confirm_card(record_id))
            except Exception as card_err:
                logger.warning(f"[聊天录入] 评估确认卡片发送失败: {card_err}")
    except DuplicateJobError as e:
        logger.info(f"[聊天录入] 查重拦截已存在岗位 | chat_id={chat_id}: {e}")
        dup = e.existing or {}
        c_name = dup.get("公司名称", "")
        j_title = dup.get("岗位名称", "")
        status = dup.get("跟进状态", "未知")
        r_url = dup.get("review_url", "")
        lines = [
            "⚠️ 识别到该岗位与表格中已有记录疑似重复：",
            f"• 岗位：{c_name} - {j_title}",
            f"• 状态：{status}",
        ]
        if r_url:
            lines.append(f"👉 查看已有记录：{r_url}")
        lines.append("\n为避免重复评估，本次未建新档案。若确属不同岗位，可在 Web 端「极速录入」勾选「确认非重复」录入。")
        await send_feishu_message(chat_id, "\n".join(lines), "chat_id")
    except InvalidJobFieldsError as e:
        logger.warning(f"[聊天录入] 岗位核心字段缺失 | chat_id={chat_id}: {e.missing}")
        missing_str = "、".join(e.missing)
        await send_feishu_message(
            chat_id,
            f"⚠️ 截图未能完整提取核心字段（{missing_str}），为避免产生垃圾记录未予建档。\n建议：可直接在此聊天框粘贴纯文本 JD（同样自动解析建岗），或补发包含完整职位描述与公司名的清晰截图。",
            "chat_id",
        )
    except Exception as e:
        logger.exception(f"[聊天录入] 截图识别录入失败 | chat_id={chat_id}: {e}")
        await send_feishu_message(
            chat_id,
            f"❌ 岗位截图识别录入失败：{e}\n可重发截图，或直接粘贴 JD 文字（同样自动解析）。",
            "chat_id",
        )


async def handle_unsupported_message(chat_id: str, msg_type: str) -> None:
    """暂不支持的消息类型：给用户明确提示，而非静默丢弃。"""
    logger.info(f"[聊天录入] 不支持的消息类型 type={msg_type} | chat_id={chat_id}，已回复提示")
    await send_feishu_message(chat_id, _UNSUPPORTED_HINT, "chat_id")


# ==========================================
# 岗位链接补录（截图录入后的反问闭环）
# ==========================================
def should_intercept_link_reply(chat_id: str, text: str) -> bool:
    """该会话在等岗位链接，且回复内容是链接或明确跳过 —— 拦截后不再进 ChatOps Agent。"""
    if chat_id not in _pending_job_links:
        return False
    t = (text or "").strip()
    return bool(_URL_PATTERN.search(t)) or t.lower() in _SKIP_LINK_WORDS


def clear_pending_link(chat_id: str) -> bool:
    """用户回复了别的内容（已转投 Agent），静默清除待补录状态避免未来误拦截。"""
    return _pop_pending_link(chat_id) is not None


async def handle_link_reply(chat_id: str, text: str) -> None:
    """处理链接补录回复：提取 URL 更新多维表格岗位记录，或按「跳过」结束。

    先写表成功再消费待补录状态：写表失败时保留状态并告知重试——旧实现先撕纸条，
    写表失败后用户再发的链接不再进补录通道，且收不到任何反馈。
    """
    record_id = _pending_job_links.get(chat_id)
    if not record_id:
        return
    t = (text or "").strip()
    if t.lower() in _SKIP_LINK_WORDS:
        logger.info(f"[聊天录入] 用户跳过岗位链接补录 | record_id={record_id}")
        _pop_pending_link(chat_id)
        await send_feishu_message(chat_id, "好的，已跳过岗位链接补录。想跑评估随时点上方按钮或回复「评估这个岗位」。", "chat_id")
        return

    match = _URL_PATTERN.search(t)
    if not match:
        _pop_pending_link(chat_id)
        await send_feishu_message(chat_id, "没识别到链接，已取消补录；需要的话重新发链接即可。", "chat_id")
        return

    url = match.group(0).rstrip('.,;）)、">')
    from app.core.feishu_client import feishu_client
    from app.jobs.service import normalize_job_url

    desktop_url = normalize_job_url(url)
    converted = "（手机链接已自动转为电脑端链接）" if desktop_url != url else ""
    try:
        await feishu_client.update_record(
            settings.FEISHU_TABLE_ID_JOBS,
            record_id,
            {"岗位链接": {"link": desktop_url, "text": "点击查看"}},
        )
    except Exception as e:
        logger.warning(f"[聊天录入] 岗位链接补录写表失败（保留待补录状态）| record_id={record_id}: {e}")
        await send_feishu_message(
            chat_id,
            "⚠️ 链接写入多维表格失败，请直接重发一次链接（这条补录仍然有效）。",
            "chat_id",
        )
        return
    _pop_pending_link(chat_id)  # 写表成功才消费状态
    logger.info(f"[聊天录入] 岗位链接已补录 | record_id={record_id} | url={desktop_url}")
    await send_feishu_message(
        chat_id,
        f"✅ 岗位链接已补录到该岗位{converted}，可点卡片复核字段。想跑评估随时点上方按钮或回复「评估这个岗位」。",
        "chat_id",
    )


# ==========================================
# 单岗位评估确认（录入后的反问闭环；区别于指挥中心「全链路」= 批量抓取→清洗→评估→自动投递）
# ==========================================
_PIPELINE_TRIGGER_WORDS = ("评估这个岗位", "评估一下", "跑评估", "开始评估", "走全链路", "全链路")
_PIPELINE_DECLINE_WORDS = ("先放着", "不用了", "暂不", "不用跑")

# 「评估这个岗位」与指挥中心「全链路」的名词区分说明（用户点「📖 什么是全链路？」时回复）
PIPELINE_EXPLAIN_TEXT = (
    "📖 两种「链路」的区别：\n\n"
    "1️⃣ 评估这个岗位（当前按钮，单岗位评估链路）\n"
    "针对你刚发的这一个岗位：AI 初评 → 深度评估 → 简历改写/话术 → 物料产出，"
    "然后停下来等你复核，绝不自动投递。适合你自己刷到/别人推荐的岗位。\n\n"
    "2️⃣ 全链路（网页指挥中心里的叫法，批量求职链路）\n"
    "系统自动跑：全网抓取 → 清洗 → 批量评估 → 改写 → 自动投递。适合让系统自动找岗位自动投。\n\n"
    "两者完全独立：这里的评估只处理你手动发进来的岗位，不会碰自动投递。"
)


def build_pipeline_confirm_card(record_id: str) -> dict[str, Any]:
    """评估确认卡片：单个回传按钮（点击触发卡片回调 card.action.trigger），底部灰色小字提示。"""
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "🎯 接下来做什么？"},
        },
        "elements": [
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "🚀 评估这个岗位"},
                        "type": "primary",
                        "value": {"action": "run_pipeline", "record_id": record_id},
                    },
                ],
            },
            {
                "tag": "note",
                "elements": [{
                    "tag": "plain_text",
                    "content": "💡 如需对岗位进行 AI 评估、简历改写与打招呼语产出，请点击上方按钮；完成后会停在复核断点等你确认，绝不自动投递。",
                }],
            },
        ],
    }


# ==========================================
# 卡片动作节流：双击/飞书回调重放防重（run_pipeline 另有 inflight 守卫，这里覆盖其余动作）
# ==========================================
_CARD_ACTION_TS: dict[str, float] = {}


def _card_action_throttled(chat_id: str, action: str, key: str = "", window: float = 10.0) -> bool:
    """同一 chat 同一动作同一目标在 window 秒内只放行一次。返回 True 表示本次应忽略。"""
    k = f"{chat_id}|{action}|{key}"
    now = time.monotonic()
    if now - _CARD_ACTION_TS.get(k, 0.0) < window:
        logger.info(f"[聊天录入] 卡片动作节流命中，忽略重放/双击 | {k}")
        return True
    _CARD_ACTION_TS[k] = now
    if len(_CARD_ACTION_TS) > 1000:  # 只进不出的节流账本定期瘦身
        for k2 in list(_CARD_ACTION_TS)[:500]:
            _CARD_ACTION_TS.pop(k2, None)
    return False


async def handle_card_action(chat_id: str, value: dict[str, Any]) -> None:
    """卡片按钮点击的统一处理入口（卡片回调 card.action.trigger 落到这里分发）。"""
    action = str((value or {}).get("action") or "")
    record_id = str((value or {}).get("record_id") or "")
    logger.info(f"[聊天录入] 卡片按钮点击 | chat_id={chat_id} | action={action} | record_id={record_id}")

    if action == "run_pipeline":
        if not record_id:
            await send_feishu_message(chat_id, "⚠️ 按钮缺少岗位标识，请重新发送岗位截图后再试。", "chat_id")
            return
        if record_id in _inflight_pipelines:
            logger.info(f"[聊天录入] 该岗位流水线已在执行中，忽略重复点击 | record_id={record_id}")
            await send_feishu_message(chat_id, "⏳ 这个岗位的评估已经在跑了，完成后会通知你。", "chat_id")
            return
        await _launch_single_job_pipeline(chat_id, record_id)
    elif action == "select_job":
        if not record_id:
            await send_feishu_message(chat_id, "⚠️ 按钮缺少岗位标识，请重新操作。", "chat_id")
            return
        if _card_action_throttled(chat_id, action, record_id, window=10.0):
            return
        from app.services.resume_edit_chat import handle_candidate_selected

        await handle_candidate_selected(chat_id, record_id)
    elif action == "mark_delivered":
        if not record_id:
            await send_feishu_message(chat_id, "⚠️ 按钮缺少岗位标识，请重新发送岗位截图后再试。", "chat_id")
            return
        if _card_action_throttled(chat_id, action, record_id, window=10.0):
            return
        from app.services.resume_edit_chat import mark_delivered_record

        await mark_delivered_record(chat_id, record_id)
    elif action == "explain_pipeline":
        if _card_action_throttled(chat_id, action, "", window=5.0):
            return
        await send_feishu_message(chat_id, PIPELINE_EXPLAIN_TEXT, "chat_id")
    elif action == "send_prompt":
        prompt = str((value or {}).get("prompt") or "").strip()
        if not prompt:
            await send_feishu_message(chat_id, "⚠️ 缺少指令内容。", "chat_id")
            return
        if _card_action_throttled(chat_id, action, f"{record_id}|{prompt}", window=15.0):
            return
        if record_id:
            from app.services.resume_edit_chat import record_edit_target
            record_edit_target(chat_id, record_id)
        from app.services.chat_agent.agent import handle_agent_message
        await handle_agent_message(chat_id, prompt)
    elif action == "update_status":
        target_status = str((value or {}).get("target_status") or "").strip()
        if not record_id or not target_status:
            await send_feishu_message(chat_id, "⚠️ 缺少岗位或目标状态参数。", "chat_id")
            return
        if _card_action_throttled(chat_id, action, f"{record_id}|{target_status}", window=10.0):
            return
        from app.core.config import settings
        from app.core.feishu_client import feishu_client
        from app.services.chat_agent.card_builder import build_job_selected_card
        from app.services.feishu_service import update_feishu_record
        from app.services.resume_edit_chat import record_edit_target

        record_edit_target(chat_id, record_id)
        await asyncio.to_thread(update_feishu_record, record_id, {"跟进状态": target_status})

        rec = await feishu_client.fetch_bitable_record_by_id(settings.FEISHU_TABLE_ID_JOBS, record_id)
        fields = (rec or {}).get("fields", {}) or {}
        company = fields.get("公司名称") or "目标公司"
        job = fields.get("岗位名称") or "目标岗位"
        salary = fields.get("薪资") or "面议"
        city = fields.get("城市") or "全国"

        card = build_job_selected_card(
            {
                "company": company,
                "title": job,
                "salary": salary,
                "city": city,
                "status": target_status,
                "platform": fields.get("招聘平台", ""),
                "grade": fields.get("综合评级 (A-F)", ""),
            },
            record_id=record_id,
        )
        try:
            await send_feishu_card(chat_id, card)
        except Exception:
            await send_feishu_message(chat_id, f"✅ 已将【{company} · {job}】跟进状态更新为「{target_status}」！", "chat_id")
    elif action == "send_materials":
        if not record_id:
            await send_feishu_message(chat_id, "⚠️ 缺少岗位标识。", "chat_id")
            return
        if _card_action_throttled(chat_id, action, record_id, window=30.0):
            return
        from app.services.resume_edit_chat import record_edit_target
        record_edit_target(chat_id, record_id)

        import re
        import tempfile
        from pathlib import Path as _Path

        from app.automation.materials import _render_custom_resume_materials
        from app.core import feishu_utils
        from app.core.config import settings
        from app.core.feishu_client import feishu_client
        from app.core.feishu_messaging import (
            send_feishu_file,
            send_feishu_image,
            upload_file_to_feishu,
            upload_image_to_feishu,
        )
        from app.services.resume_edit_chat import _load_resume_base, _merge_privacy

        rec = await feishu_client.fetch_bitable_record_by_id(settings.FEISHU_TABLE_ID_JOBS, record_id)
        fields = (rec or {}).get("fields", {}) or {}
        pdf_att = fields.get("PDF备份") or fields.get("PDF 备份") or []
        img_att = fields.get("图片保存") or []
        greeting = fields.get("打招呼语") or ""

        # 1. 优先发送打招呼语
        if greeting:
            greeting_text = greeting if isinstance(greeting, str) else "".join(x.get("text", "") for x in greeting if isinstance(x, dict))
            if greeting_text.strip():
                await send_feishu_message(chat_id, f"💬 **打招呼语**：\n{greeting_text.strip()}", "chat_id")

        # 2. 如果已有附件，直接下载并发送
        sent_files = False
        # 区分「本来没附件」与「有附件但发送失败」：后者绝不能走即时渲染并覆盖
        # 表里的历史附件（一次网络抖动就会把沉淀的正式物料冲掉）
        has_attachments = bool(pdf_att or img_att)
        send_failed = False
        if has_attachments:
            for att_list, is_img, default_ext in ((img_att, True, ".jpg"), (pdf_att, False, ".pdf")):
                if isinstance(att_list, list):
                    for item in att_list:
                        token = item.get("file_token")
                        name = item.get("name") or f"物料{default_ext}"
                        if not token:
                            continue
                        tmp = ""
                        try:
                            with tempfile.NamedTemporaryFile(suffix=default_ext, delete=False) as f:
                                tmp = f.name
                            ok = await asyncio.to_thread(feishu_utils.download_feishu_file, token, tmp)
                            if not ok:
                                send_failed = True
                                continue
                            data = await asyncio.to_thread(_Path(tmp).read_bytes)
                            if is_img:
                                sent = bool(await send_feishu_image(chat_id, await upload_image_to_feishu(data)))
                            else:
                                sent = bool(await send_feishu_file(chat_id, await upload_file_to_feishu(data, name)))
                            if sent:
                                sent_files = True
                            else:
                                send_failed = True
                        except Exception as err:
                            logger.warning(f"物料发送异常 {name}: {err}")
                            send_failed = True
                        finally:
                            if tmp:
                                _Path(tmp).unlink(missing_ok=True)
            if send_failed:
                await send_feishu_message(
                    chat_id,
                    "⚠️ 物料在表格附件中已存在，但本次发送失败（网络波动）。可直接在多维表格附件列下载，或稍后重试发送。",
                    "chat_id",
                )

        # 3. 只有「本来就没有附件」时才即时渲染补齐（发送失败走上面分支，不覆盖历史附件）
        if not has_attachments and not sent_files:
            resume_data = await _load_resume_base(record_id)
            if resume_data:
                await send_feishu_message(chat_id, "📄 正在为你即时渲染定制简历 PDF 与长图（约需 3~5 秒）…", "chat_id")
                await _merge_privacy(resume_data)

                def _txt(v: Any) -> str:
                    if isinstance(v, str):
                        return v.strip()
                    if isinstance(v, list):
                        return "".join(x.get("text", "") for x in v if isinstance(x, dict)).strip()
                    return str(v or "").strip()

                company = _txt(fields.get("公司名称")) or "目标公司"
                job = _txt(fields.get("岗位名称")) or "目标岗位"
                cleaned_name = re.sub(r'[\/\\:\*\?"<>\|\s]+', '_', f"{company}_{job}").strip('_') or "定制简历"

                mats = await _render_custom_resume_materials(resume_data, cleaned_name)
                if mats:
                    # 异步回写飞书多维表格附件
                    try:
                        await feishu_client.update_record(settings.FEISHU_TABLE_ID_JOBS, record_id, {
                            "PDF备份": [{"file_token": mats["pdf_token"], "name": f"{mats['name']}.pdf"}],
                            "图片保存": [{"file_token": mats["img_token"], "name": f"{mats['name']}-长图.jpg"}],
                        })
                    except Exception as e:
                        logger.warning(f"回写新生成物料附件失败: {e}")

                    # 发送新生成的长图与 PDF
                    for token, is_img, fname in ((mats["img_token"], True, f"{mats['name']}-长图.jpg"),
                                                 (mats["pdf_token"], False, f"{mats['name']}.pdf")):
                        tmp = ""
                        try:
                            with tempfile.NamedTemporaryFile(suffix=".jpg" if is_img else ".pdf", delete=False) as f:
                                tmp = f.name
                            ok = await asyncio.to_thread(feishu_utils.download_feishu_file, token, tmp)
                            if not ok:
                                continue
                            data = await asyncio.to_thread(_Path(tmp).read_bytes)
                            if is_img:
                                await send_feishu_image(chat_id, await upload_image_to_feishu(data))
                            else:
                                await send_feishu_file(chat_id, await upload_file_to_feishu(data, fname))
                            sent_files = True
                        except Exception as e:
                            logger.warning(f"即时物料发送异常 {fname}: {e}")
                        finally:
                            if tmp:
                                _Path(tmp).unlink(missing_ok=True)

            if not sent_files and not greeting:
                await send_feishu_message(chat_id, "ℹ️ 该岗位暂未生成专属物料（PDF/长图/招呼语），可先点击「🚀 发起 AI 全面评估」生成。", "chat_id")
    else:
        logger.warning(f"[聊天录入] 未知的卡片动作: {action}")


def should_intercept_pipeline_confirm(chat_id: str, text: str) -> bool:
    """该会话在等评估确认，且回复是触发词或婉拒 —— 文本兜底（主交互是卡片按钮）。"""
    if chat_id not in _pending_pipeline:
        return False
    t = (text or "").strip()
    return any(w in t for w in _PIPELINE_TRIGGER_WORDS) or t in _PIPELINE_DECLINE_WORDS


def clear_pending_pipeline(chat_id: str) -> bool:
    """用户回复了别的内容（已转投 Agent），静默清除待确认状态避免未来误拦截。"""
    return _pending_pipeline.pop(chat_id, None) is not None


async def handle_pipeline_confirm(chat_id: str, text: str) -> None:
    """处理评估确认回复（文本兜底路径）：触发单岗位流水线，或按婉拒结束。"""
    record_id = _pending_pipeline.pop(chat_id, None)
    if not record_id:
        return
    t = (text or "").strip()
    if t in _PIPELINE_DECLINE_WORDS:
        logger.info(f"[聊天录入] 用户暂不评估 | record_id={record_id}")
        await send_feishu_message(chat_id, "好的，这个岗位先放着；想跑的时候点上方按钮或回复「评估这个岗位」即可。", "chat_id")
        return
    await _launch_single_job_pipeline(chat_id, record_id)


# 评估报告渲染已拆分至 app/services/eval_report.py（re-export 保持既有引用/测试路径）
# 评估进度卡/启动/恢复执行器已拆分至 app/services/eval_pipeline_feedback.py（re-export 保持既有引用）
from app.services.eval_pipeline_feedback import (  # noqa: E402,F401
    _PROGRESS_STAGES,
    _RESUME_STALE_SECONDS,
    _inflight_pipelines,
    _launch_single_job_pipeline,
    _mark_card_failed,
    _resume_one_inflight,
    _run_pipeline_with_feedback,
    build_progress_card,
    resume_inflight_evaluations,
)
from app.services.eval_report import (  # noqa: E402,F401
    _EVAL_REPORT_FIELD,
    _ensure_eval_report_field,
    _generate_eval_report_image,
    _store_eval_report_attachment,
    build_eval_report_html,
)

# 物料交付已拆分至 app/services/materials_delivery.py（re-export 保持既有引用/测试路径）
from app.services.materials_delivery import (  # noqa: E402
    _deliver_materials_to_chat,  # noqa: E402,F401
)
