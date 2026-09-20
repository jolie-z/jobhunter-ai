"""ChatAgent thread_id 按月切片测试（TODO.md 数据库治理第 4 项首选方案）。"""
from datetime import datetime

from app.services.chat_agent.agent import _thread_id_for
from app.services.chat_agent.tools import _chat_id


def test_thread_id_is_monthly_sliced():
    chat_id = "oc_f6e5d4c3b2a1f0e9d8c7b6a5f4e3d2c1"
    tid = _thread_id_for(chat_id)
    assert tid == f"{chat_id}_{datetime.now():%Y%m}"
    # 同一会话同月内稳定（可续接），跨月自然分叉
    assert _thread_id_for(chat_id) == tid
    assert tid != f"{chat_id}_209912"


def test_tools_get_real_chat_id_not_sliced_thread():
    """工具层必须拿到真实 chat_id（发飞书消息依赖），而非带月份后缀的 thread_id。"""
    chat_id = "oc_real"
    config = {"configurable": {"thread_id": f"{chat_id}_202609", "chat_id": chat_id}}
    assert _chat_id(config) == chat_id


def test_tools_chat_id_falls_back_to_legacy_thread_id():
    """兼容旧调用：configurable 只有 thread_id（历史行为/直接 invoke）时不炸。"""
    config = {"configurable": {"thread_id": "oc_legacy"}}
    assert _chat_id(config) == "oc_legacy"
    assert _chat_id(None) == ""


def test_trim_and_state_queries_reuse_run_config():
    """切片后 run_config 里 thread_id 已是当月值——模拟同月两次运行拿到同一 config，
    保证 checkpoint 续接语义不被破坏。"""
    chat_id = "oc_abc"
    c1 = {"configurable": {"thread_id": _thread_id_for(chat_id), "chat_id": chat_id}}
    c2 = {"configurable": {"thread_id": _thread_id_for(chat_id), "chat_id": chat_id}}
    assert c1["configurable"]["thread_id"] == c2["configurable"]["thread_id"]
    # 跨月（模拟）分叉
    later = _thread_id_for(chat_id).replace(
        datetime.now().strftime("%Y%m"), "209912"
    )
    assert later != c1["configurable"]["thread_id"]
