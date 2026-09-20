# 📂 backend/scripts/analyze_chat_context_composition.py
"""ChatAgent 上下文构成离线诊断（token 优化第 0 步）。

回答一个问题：thread:run 每轮 7 万+ prompt tokens 到底花在哪？

数据来源（只读，不改任何库）：
1. backend/data/agent_chat_checkpoints.db —— AsyncSqliteSaver 存的会话消息，
   用 langgraph 官方反序列化路径还原每个 thread 最新状态的全量 messages。
2. agent.py 的 SYSTEM_PROMPT + tools.py 的 CHAT_TOOLS schema —— 每轮固定重复发送的静态块。

估算口径：tiktoken cl100k_base（与 MiMo 分词器有出入，但用于看构成比例足够）；
每轮 API 侧的精确 prompt_tokens 已有 token_log，本脚本负责给出「钱花在哪个部件」的分布。

用法：cd backend && .venv/bin/python scripts/analyze_chat_context_composition.py
"""
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tiktoken  # noqa: E402

DB = Path(__file__).resolve().parents[1] / "data" / "agent_chat_checkpoints.db"
SUMMARY_PREFIX = "【历史对话摘要】"
enc = tiktoken.get_encoding("cl100k_base")


def _tok(s: str) -> int:
    return len(enc.encode(s or ""))


def _msg_content_str(msg) -> str:
    c = msg.content
    if isinstance(c, str):
        return c
    if isinstance(c, list):  # 内容块列表
        return "\n".join(str(b.get("text", "")) for b in c if isinstance(b, dict) and b.get("text"))
    return str(c or "")


def categorize(messages: list) -> list[dict]:
    """把每条消息拆成构成部件（一条 AIMessage 可同时贡献 ai_text 与 tool_call_args）。"""
    rows = []
    for i, m in enumerate(messages):
        mtype = type(m).__name__
        if mtype == "SystemMessage":
            rows.append({"i": i, "cat": "system", "name": "", "text": _msg_content_str(m)})
        elif mtype == "HumanMessage":
            text = _msg_content_str(m)
            cat = "history_summary" if text.startswith(SUMMARY_PREFIX) else "user_msg"
            rows.append({"i": i, "cat": cat, "name": "", "text": text})
        elif mtype == "AIMessage":
            rows.append({"i": i, "cat": "ai_text", "name": "", "text": _msg_content_str(m)})
            for tc in (getattr(m, "tool_calls", None) or []):
                rows.append({
                    "i": i, "cat": "tool_call_args", "name": tc.get("name", ""),
                    "text": json.dumps(tc.get("args", {}), ensure_ascii=False),
                })
        elif mtype == "ToolMessage":
            rows.append({"i": i, "cat": "tool_result", "name": getattr(m, "name", "") or "?",
                         "text": _msg_content_str(m)})
        else:
            rows.append({"i": i, "cat": mtype.lower(), "name": "", "text": _msg_content_str(m)})
    return rows


def print_breakdown(title: str, rows: list[dict]) -> None:
    agg = defaultdict(lambda: [0, 0])
    for r in rows:
        agg[r["cat"] + (f":{r['name']}" if r["cat"] in ("tool_result", "tool_call_args") else "")][0] += 1
        agg[r["cat"] + (f":{r['name']}" if r["cat"] in ("tool_result", "tool_call_args") else "")][1] += _tok(r["text"])

    total = sum(v[1] for v in agg.values())
    print(f"\n=== {title} | 消息 {len(set(r['i'] for r in rows))} 条 | 估算 prompt ≈ {total:,} tok ===")
    for cat, (cnt, tok) in sorted(agg.items(), key=lambda kv: -kv[1][1]):
        bar = "█" * max(1, round(tok / total * 40)) if total else ""
        print(f"  {cat:<38} {cnt:>4} 条  {tok:>8,} tok  {tok / total * 100 if total else 0:5.1f}%  {bar}")


def print_top_messages(rows: list[dict], n: int = 12) -> None:
    per_msg = defaultdict(int)
    meta = {}
    for r in rows:
        per_msg[r["i"]] += _tok(r["text"])
        meta[r["i"]] = r
    print(f"\n--- 最大的 {n} 条消息 ---")
    for i, tok in sorted(per_msg.items(), key=lambda kv: -kv[1])[:n]:
        r = meta[i]
        label = r["cat"] + (f" [{r['name']}]" if r["name"] else "")
        preview = r["text"][:110].replace("\n", "⏎")
        print(f"  #{r['i']:>3} {label:<30} {tok:>7,} tok | {preview}")


async def analyze_threads() -> None:
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    conn = await aiosqlite.connect(f"file:{DB}?mode=ro", uri=True)
    saver = AsyncSqliteSaver(conn)
    async with conn.execute("SELECT DISTINCT thread_id FROM checkpoints") as cur:
        thread_ids = [r[0] for r in await cur.fetchall()]

    for tid in thread_ids:
        tup = await saver.aget_tuple({"configurable": {"thread_id": tid}})
        if not tup or not (tup.checkpoint or {}).get("channel_values", {}).get("messages"):
            print(f"\n=== thread {tid[:16]}… 无消息（跳过）")
            continue
        msgs = list(tup.checkpoint["channel_values"]["messages"])
        rows = categorize(msgs)
        print_breakdown(f"thread {tid[:20]}…（最新状态）", rows)
        print_top_messages(rows)

    await conn.close()


def measure_static() -> None:
    """测量每轮固定重复发送、与历史无关的静态块。"""
    from langchain_core.utils.function_calling import convert_to_openai_tool

    from app.services.chat_agent.agent import SYSTEM_PROMPT
    from app.services.chat_agent.tools import CHAT_TOOLS

    print("\n=== 静态块（每轮全量重发，与对话长度无关）===")
    sys_tok = _tok(SYSTEM_PROMPT)
    print(f"  system_prompt{'':<24} {sys_tok:>8,} tok")

    tools_tok = 0
    for t in CHAT_TOOLS:
        try:
            schema = convert_to_openai_tool(t)
            n = _tok(json.dumps(schema, ensure_ascii=False))
        except Exception as e:
            n = 0
            print(f"    ! {getattr(t, 'name', t)} schema 序列化失败: {e}")
        tools_tok += n
        print(f"    · {getattr(t, 'name', '?'):<34} {n:>6,} tok")
    print(f"  tools_schema x{len(CHAT_TOOLS)}{'':<14} {tools_tok:>8,} tok")
    print(f"  静态合计{'':<26} {sys_tok + tools_tok:>8,} tok / 轮")


if __name__ == "__main__":
    measure_static()
    asyncio.run(analyze_threads())
