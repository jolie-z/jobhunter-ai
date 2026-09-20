"""模块九质检缺陷修复回归测试（Q-M9-1/2/3/4/7）。

覆盖：
- Q-M9-3 查重三态：接口异常/业务错误码 → None（未知态），调用方 fail-closed 跳过不再误放行
- Q-M9-2 快捷审批扫描源：内存 task_queues ∪ pending_delivery_pool 停车场（重启恢复），resume 后清池
- Q-M9-4 审批门禁：白名单未配置放行+告警、名单内放行、名单外拒绝、缺 open_id fail-closed；
  卡片动作与文字快捷审批两入口的门禁接线
- Q-M9-1 反向同步事件链：WS bitable 记录变更 → mark_dirty（本系统 bitable 过滤）、
  webhook 事件名兼容真实 v1 名、jobs 读取侧脏标记消费者提前踢刷新
- Q-M9-7 feishu_ws logger 归入 app 层级
"""

import asyncio
import logging

import pytest

from app.core import chatops_authorizer, feishu_ws
from app.core.cache import JobCache
from app.core.chatops_authorizer import (
    get_approver_open_ids,
    is_authorized,
    is_quick_approval_text,
)


@pytest.fixture(autouse=True)
def _reset_dirty():
    JobCache._reset_for_tests()
    yield
    JobCache._reset_for_tests()


# ==========================================
# Q-M9-3 查重三态
# ==========================================
class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


def test_check_job_exists_hit_returns_record_id(monkeypatch):
    from job_processor import step2_sync_feishu as s2

    monkeypatch.setattr(s2.requests, "post", lambda *a, **k: _FakeResp(
        {"code": 0, "data": {"items": [{"record_id": "recX"}]}}))
    assert s2.check_job_exists("tok", "公司A", "岗位B", "广州") == "recX"


def test_check_job_exists_clean_miss_returns_false(monkeypatch):
    from job_processor import step2_sync_feishu as s2

    monkeypatch.setattr(s2.requests, "post", lambda *a, **k: _FakeResp(
        {"code": 0, "data": {"items": []}}))
    assert s2.check_job_exists("tok", "公司A", "岗位B", "广州") is False


def test_check_job_exists_business_error_returns_none(monkeypatch):
    """业务错误码不再当「不存在」放行，改返回未知态 None（Q-M9-3）。"""
    from job_processor import step2_sync_feishu as s2

    monkeypatch.setattr(s2.requests, "post", lambda *a, **k: _FakeResp(
        {"code": 1254043, "msg": "PermissionDenied"}))
    assert s2.check_job_exists("tok", "公司A", "岗位B", "广州") is None


def test_check_job_exists_network_exception_returns_none(monkeypatch):
    from job_processor import step2_sync_feishu as s2

    def _boom(*_a, **_k):
        raise ConnectionError("feishu down")
    monkeypatch.setattr(s2.requests, "post", _boom)
    assert s2.check_job_exists("tok", "公司A", "岗位B", "广州") is None


def test_sync_loop_skips_unknown_dedup_without_creating(monkeypatch, tmp_path):
    """主推送循环：查重未知态 → 该岗位保持待推送（不建飞书记录、不计成功）。"""
    import sqlite3

    from job_processor import step2_sync_feishu as s2

    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE jobs (company_name TEXT, job_title TEXT, city TEXT, "
                "job_link TEXT, process_status TEXT, is_synced INTEGER DEFAULT 0, "
                "feishu_record_id TEXT DEFAULT '')")
    con.execute("INSERT INTO jobs (company_name, job_title, city, job_link, process_status) "
                "VALUES ('公司A','岗位B','广州','link1','待推送至飞书')")
    con.commit()
    con.close()

    monkeypatch.setattr(s2, "check_job_exists", lambda *a, **k: None)
    created = []
    monkeypatch.setattr(s2, "push_single_record_to_feishu", lambda *_a, **_k: created.append(1) or False)

    s2.sync_sqlite_to_feishu(str(db), table_name="jobs")

    con = sqlite3.connect(db)
    row = con.execute("SELECT is_synced, process_status, feishu_record_id FROM jobs").fetchone()
    con.close()
    assert created == [], "未知态绝不冒险新建飞书记录"
    assert row[0] == 0 and row[1] == "待推送至飞书", "应保持待推送态待下轮重试"


# ==========================================
# Q-M9-2 快捷审批扫描源 ∪ 停车场
# ==========================================
class _FakeSnap:
    def __init__(self, next_nodes):
        self.next = next_nodes


class _FakePipelineApp:
    def __init__(self, breakpoint_threads):
        self.breakpoint_threads = breakpoint_threads
        self.resumed = []

    async def aget_state(self, config):
        tid = config["configurable"]["thread_id"]
        return _FakeSnap(["manual_review_node"] if tid in self.breakpoint_threads else [])

    async def astream(self, cmd, config):
        self.resumed.append(config["configurable"]["thread_id"])
        yield {}


def test_collect_threads_merges_memory_and_pool(monkeypatch):
    import app.automation.db as auto_db
    import app.tasks.state as task_state

    class _Q:
        def keys(self):
            return ["job_recAAA", "recShared"]

    monkeypatch.setattr(task_state, "task_queues", _Q())
    monkeypatch.setattr(auto_db, "get_pending_pool", lambda max_age_days=7: [
        {"record_id": "recShared"}, {"record_id": "recCCC"}])

    async def run():
        from app.services.quick_approval import collect_pending_approval_threads
        return await collect_pending_approval_threads()

    merged = asyncio.run(run())
    assert merged == ["job_recAAA", "recShared", "recCCC"], "内存∪停车场合并，重复线程号去重保序"


def test_quick_approval_resumes_pool_thread_and_cleans_pool(monkeypatch):
    """重启场景：task_queues 空、断点线程只在停车场 → 放行仍可达，且 resume 后清池。"""
    import app.automation.db as auto_db
    import app.automation.scheduler as sched
    import app.tasks.state as task_state

    class _Q:
        def keys(self):
            return set()

    fake_app = _FakePipelineApp(breakpoint_threads={"recPPP"})
    monkeypatch.setattr(task_state, "task_queues", _Q())
    monkeypatch.setattr(auto_db, "get_pending_pool", lambda max_age_days=30: [{"record_id": "recPPP"}])
    cleaned = []
    monkeypatch.setattr(auto_db, "remove_from_pending_pool", lambda ids: cleaned.extend(ids))
    monkeypatch.setattr(sched, "pipeline_app", fake_app)

    replies = []

    async def fake_send(_chat_id, text):
        replies.append(text)

    async def run():
        from app.services.quick_approval import handle_quick_approval
        await handle_quick_approval("oc_x", action="approve", send_message=fake_send)

    asyncio.run(run())
    assert fake_app.resumed == ["recPPP"], "停车场断点线程应被恢复放行"
    assert cleaned == ["recPPP"], "resume 后应从停车场移除"
    assert any("放行: 1 个" in r for r in replies), f"回执应含放行计数: {replies}"


def test_quick_approval_empty_everywhere(monkeypatch):
    import app.automation.scheduler as sched
    import app.tasks.state as task_state

    class _Q:
        def keys(self):
            return set()

    monkeypatch.setattr(task_state, "task_queues", _Q())
    monkeypatch.setattr(sched, "pipeline_app", _FakePipelineApp(breakpoint_threads=set()))

    replies = []

    async def fake_send(_chat_id, text):
        replies.append(text)

    async def run():
        from app.services.quick_approval import handle_quick_approval
        await handle_quick_approval("oc_x", action="approve", send_message=fake_send)

    asyncio.run(run())
    assert any("没有待审批" in r for r in replies)


# ==========================================
# Q-M9-4 审批门禁
# ==========================================
@pytest.fixture(autouse=True)
def _reset_warn_flag(monkeypatch):
    monkeypatch.setattr(chatops_authorizer, "_empty_warned", False)


def test_authorizer_unset_allows(monkeypatch):
    monkeypatch.setenv("FEISHU_APPROVER_OPEN_IDS", "")
    monkeypatch.setattr("app.core.config.settings.FEISHU_APPROVER_OPEN_IDS", None, raising=False)
    assert get_approver_open_ids() == []
    assert is_authorized("ou_anyone", "update_status") is True


def test_authorizer_list_enforced(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.FEISHU_APPROVER_OPEN_IDS", "ou_boss, ou_alice", raising=False)
    assert is_authorized("ou_boss", "update_status") is True
    assert is_authorized("ou_boss ", "update_status") is True, "容忍首尾空白"
    assert is_authorized("ou_mallory", "update_status") is False
    assert is_authorized(None, "update_status") is False, "缺 open_id fail-closed"


def test_is_quick_approval_text():
    assert is_quick_approval_text("放行") and is_quick_approval_text(" Approve ")
    assert is_quick_approval_text("帮我放行一下岗位") is False, "精确词表，不误伤自然语言"


class _FakeOperator:
    def __init__(self, open_id):
        self.open_id = open_id


class _FakeCardAction:
    def __init__(self, value):
        self.value = value


class _FakeCardEvent:
    def __init__(self, action_value, open_id):
        self.action = _FakeCardAction(action_value)
        self.operator = _FakeOperator(open_id)
        from types import SimpleNamespace
        self.context = SimpleNamespace(open_chat_id="oc_chat1")


class _FakeCardData:
    def __init__(self, action_value, open_id):
        self.event = _FakeCardEvent(action_value, open_id)


def _with_card_spies(monkeypatch, dispatched):
    monkeypatch.setattr(feishu_ws, "_dispatch_coroutine",
                        lambda coro: (dispatched.append(coro), coro.close()))
    import app.services.report_card_actions as rca
    monkeypatch.setattr(rca, "is_report_card_action", lambda a: False)


def test_card_action_denied_for_outsider(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.FEISHU_APPROVER_OPEN_IDS", "ou_boss", raising=False)
    dispatched = []
    _with_card_spies(monkeypatch, dispatched)
    resp = feishu_ws._on_card_action(_FakeCardData(
        {"action": "update_status", "record_id": "rec1", "target_status": "待投递"}, "ou_mallory"))
    assert dispatched == [], "名单外操作者不得进入处理链"
    assert "审批权限" in str(resp.toast.content or "")


def test_card_action_allowed_for_approver(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.FEISHU_APPROVER_OPEN_IDS", "ou_boss", raising=False)
    dispatched = []
    _with_card_spies(monkeypatch, dispatched)
    feishu_ws._on_card_action(_FakeCardData(
        {"action": "update_status", "record_id": "rec1", "target_status": "待投递"}, "ou_boss"))
    assert len(dispatched) == 1


class _Msg:
    def __init__(self, text, msg_id, sender_open_id):
        import json
        import time
        self.message_type = "text"
        self.chat_id = "oc_chat1"
        self.message_id = msg_id
        self.create_time = str(int(time.time() * 1000))
        self.content = json.dumps({"text": text}, ensure_ascii=False)
        self._oid = sender_open_id

    def __getattr__(self, name):
        if name == "root_id":
            return None
        raise AttributeError(name)


class _Sender:
    def __init__(self, oid):
        from types import SimpleNamespace
        self.sender_type = "user"
        self.sender_id = SimpleNamespace(open_id=oid)


class _Event:
    def __init__(self, msg):
        self.message = msg
        self.sender = _Sender(msg._oid)


class _Data:
    def __init__(self, msg):
        self.event = _Event(msg)


# ----------------------------------------
# B2 单测级：feishu_ws 守卫链（补回：R2 审查版测试文件曾丢失本组）
# ----------------------------------------
def test_ws_guard_app_sender_dropped_before_dedup(monkeypatch):
    """机器人自身消息（sender_type=app）必须在幂等锁之前被丢弃。"""
    dedup_calls = []
    monkeypatch.setattr("app.core.feishu_msg_dedup.check_and_mark", lambda mid: dedup_calls.append(mid) or True)

    class _AppSender:
        sender_type = "app"
        sender_id = None

    msg = _Msg("自发自收回流消息", "om_m9_app_x", "ou_self")
    msg.event_sender = None

    class _Evt:
        def __init__(self, m):
            self.message = m
            self.sender = _AppSender()

    class _D:
        def __init__(self, evt):
            self.event = evt

    dropped = []
    monkeypatch.setattr(feishu_ws, "_dispatch_coroutine", lambda coro: dropped.append(1) or coro.close())
    feishu_ws._on_message_receive(_D(_Evt(msg)))
    assert dropped == [], "app 消息不得进入任何下游分发"
    assert dedup_calls == [], "发送者守卫应先于幂等锁触发"


def test_ws_guard_stale_message_dropped(monkeypatch):
    """超过 300 秒的过期消息丢弃。"""
    dropped = []
    monkeypatch.setattr(feishu_ws, "_dispatch_coroutine", lambda coro: dropped.append(1) or coro.close())
    monkeypatch.setattr("app.core.feishu_msg_dedup.check_and_mark", lambda mid: True)
    feishu_ws._on_message_receive(_StaleData())
    assert dropped == []


class _StaleData:
    """过期消息事件（create_time 直接给 600 秒前）。"""

    def __init__(self):
        import time as _t
        from types import SimpleNamespace
        msg = SimpleNamespace(
            message_type="text", chat_id="oc_chat1", message_id=f"om_stale_{_t.time_ns()}",
            create_time=str(int((_t.time() - 600) * 1000)),
            content=__import__("json").dumps({"text": "过期消息"}),
        )
        sender = SimpleNamespace(sender_type="user", sender_id=SimpleNamespace(open_id="ou_x"))
        self.event = SimpleNamespace(message=msg, sender=sender)


def test_ws_idempotency_duplicate_dropped(monkeypatch):
    """同一 message_id 第二次到达必须被幂等锁丢弃（进程内假库，不触生产 seen 文件）。"""
    seen = set()
    monkeypatch.setattr("app.core.feishu_msg_dedup.check_and_mark",
                        lambda mid: False if mid in seen else (seen.add(mid) or True))
    sent = []
    monkeypatch.setattr("app.services.feishu_service.send_feishu_message",
                        lambda chat_id, text, *a, **k: sent.append(text))
    dropped = []
    monkeypatch.setattr(feishu_ws, "_dispatch_coroutine", lambda coro: dropped.append(1) or coro.close())

    mid = f"om_m9_dup_{_t_ns()}"
    feishu_ws._on_message_receive(_Data(_Msg("ping", mid, "ou_x")))
    feishu_ws._on_message_receive(_Data(_Msg("ping", mid, "ou_x")))
    assert len(sent) == 1, "首条 ping 回 pong，重复消息不得二次回复"


def test_ws_ping_pong_direct(monkeypatch):
    """ping/测试/test 直通回复，不进 ChatAgent。"""
    sent = []
    monkeypatch.setattr("app.services.feishu_service.send_feishu_message",
                        lambda chat_id, text, *a, **k: sent.append(text))
    monkeypatch.setattr("app.core.feishu_msg_dedup.check_and_mark", lambda mid: True)
    dropped = []
    monkeypatch.setattr(feishu_ws, "_dispatch_coroutine", lambda coro: dropped.append(1) or coro.close())
    feishu_ws._on_message_receive(_Data(_Msg("ping", f"om_m9_ping_{_t_ns()}", "ou_x")))
    assert dropped == []
    assert sent and "pong" in sent[0]


def _t_ns():
    import time as _t
    return _t.time_ns()


# ----------------------------------------
# A2 机制：webhook bitable 事件 → mark_dirty（补回）
# ----------------------------------------
def test_webhook_bitable_marks_dirty_only(monkeypatch):
    from app.api.routes import webhook

    dirty_calls = []
    monkeypatch.setattr("app.core.cache.JobCache.mark_dirty", lambda: dirty_calls.append(1))

    webhook._process_webhook_event({"header": {"event_type": "bitable.record.changed"}, "event": {}})
    assert sum(dirty_calls) == 1, "bitable 事件应触发 mark_dirty"

    dirty_calls.clear()
    webhook._process_webhook_event(
        {"header": {"event_type": "im.message.receive_v1"},
         "event": {"message": {}, "sender": {"sender_type": "user"}}})
    assert dirty_calls == [], "非 bitable 事件不得触发 mark_dirty"



def test_text_quick_approval_denied_at_message_layer(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.FEISHU_APPROVER_OPEN_IDS", "ou_boss", raising=False)
    dispatched = []
    monkeypatch.setattr(feishu_ws, "_dispatch_to_agent", lambda *a, **k: dispatched.append("agent"))
    sent = []
    monkeypatch.setattr("app.services.feishu_service.send_feishu_message",
                        lambda chat_id, text, *a, **k: sent.append(text))
    # 拒绝回执经 _dispatch_coroutine(to_thread) 异步发出：让本轮唯一的 dispatch 真实执行
    monkeypatch.setattr(feishu_ws, "_dispatch_coroutine", lambda coro: asyncio.run(coro))
    # 去重存储用进程内假库，绝不读写生产 data/feishu_seen_msg_ids.json
    monkeypatch.setattr("app.core.feishu_msg_dedup.check_and_mark", lambda mid: True)
    from app.services.chat_agent import agent as chat_agent
    monkeypatch.setattr(chat_agent, "is_ready", lambda: False)

    feishu_ws._on_message_receive(_Data(_Msg("放行", "om_denied_m9", "ou_mallory")))
    assert dispatched == [], "名单外的文字快捷审批不得下发"
    assert any("审批权限" in t for t in sent)


def test_text_quick_approval_allowed_for_approver(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.FEISHU_APPROVER_OPEN_IDS", "ou_boss", raising=False)
    dispatched = []
    monkeypatch.setattr(feishu_ws, "_dispatch_coroutine", lambda coro: dispatched.append(coro) or coro.close())
    monkeypatch.setattr(feishu_ws, "_dispatch_to_agent", lambda *a, **k: dispatched.append("agent"))
    sent = []
    monkeypatch.setattr("app.services.feishu_service.send_feishu_message",
                        lambda chat_id, text, *a, **k: sent.append(text))
    monkeypatch.setattr("app.core.feishu_msg_dedup.check_and_mark", lambda mid: True)
    from app.services.chat_agent import agent as chat_agent
    monkeypatch.setattr(chat_agent, "is_ready", lambda: False)

    feishu_ws._on_message_receive(_Data(_Msg("放行", "om_allow_m9", "ou_boss")))
    assert "agent" in dispatched, "名单内放行应正常下发老 Agent 快捷审批"


# ==========================================
# Q-M9-1 反向同步事件链
# ==========================================
class _FakeBitableEvent:
    def __init__(self, file_token, table_id):
        self.file_token = file_token
        self.table_id = table_id


class _FakeBitableData:
    def __init__(self, file_token, table_id):
        self.event = _FakeBitableEvent(file_token, table_id)


def test_ws_bitable_event_marks_dirty_for_own_app(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.FEISHU_APP_TOKEN", "tokOWN", raising=False)
    feishu_ws._on_bitable_record_changed(_FakeBitableData("tokOWN", "tblJOBS"))
    assert JobCache.is_dirty() is True


def test_ws_bitable_event_ignores_foreign_app(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.FEISHU_APP_TOKEN", "tokOWN", raising=False)
    feishu_ws._on_bitable_record_changed(_FakeBitableData("tokOTHER", "tblOther"))
    assert JobCache.is_dirty() is False


def test_webhook_matches_real_v1_event_name():
    from app.api.routes.webhook import _handle_bitable_event
    assert _handle_bitable_event("drive.v1.file.bitable_record_changed") is True, "真实 v1 事件名必须命中"
    assert _handle_bitable_event("bitable.record.changed") is True, "兼容历史前缀"
    assert _handle_bitable_event("im.message.receive_v1") is False


def test_jobs_read_consumes_dirty_flag(monkeypatch):
    """缓存新鲜但脏 → 首个读取提前踢后台刷新（事件链消费端）。"""
    import app.jobs.service as js

    JobCache._data = [{"record_id": "rec1"}]
    JobCache._timestamp = __import__("time").time()
    JobCache._dirty = True
    kicks = []
    monkeypatch.setattr(js, "_kick_background_refresh", lambda: kicks.append(1))
    _ = asyncio.run(js.fetch_and_clean_all_jobs(force=False))
    assert kicks == [1], "脏标记应触发提前刷新"


def test_jobs_read_clean_cache_no_kick(monkeypatch):
    import app.jobs.service as js

    JobCache._data = [{"record_id": "rec1"}]
    JobCache._timestamp = __import__("time").time()
    JobCache._dirty = False
    kicks = []
    monkeypatch.setattr(js, "_kick_background_refresh", lambda: kicks.append(1))
    _ = asyncio.run(js.fetch_and_clean_all_jobs(force=False))
    assert kicks == []


# ==========================================
# Q-M9-7 logger 归入 app 层级
# ==========================================
def test_feishu_ws_logger_under_app_hierarchy():
    assert logging.getLogger("app.core.feishu_ws") is feishu_ws.logger, \
        "logger 必须挂在 app 层级下，否则 INFO 被 root WARNING 拦截（console_stream 放开失效）"


def test_refresh_preserves_dirty_arrived_during_fetch(monkeypatch):
    """定序回归：拉取期间新到的 mark_dirty 不得被 set() 吞掉（丢失更新防护）。"""
    import app.jobs.service as js

    calls = {"pulls": 0}

    async def fake_pull():
        calls["pulls"] += 1
        JobCache.mark_dirty()  # 模拟拉取期间飞书侧又发生外部变动
        return [{"record_id": f"rec{calls['pulls']}"}]

    monkeypatch.setattr(js, "_pull_jobs_from_feishu", fake_pull)
    _ = asyncio.run(js.fetch_and_clean_all_jobs(force=True))
    assert JobCache.is_dirty() is True, "刷新窗口内到达的脏标记必须保留待下轮消费"


def test_refresh_clean_fetch_leaves_clean(monkeypatch):
    import app.jobs.service as js

    async def fake_pull():
        return [{"record_id": "rec1"}]

    monkeypatch.setattr(js, "_pull_jobs_from_feishu", fake_pull)
    _ = asyncio.run(js.fetch_and_clean_all_jobs(force=True))
    assert JobCache.is_dirty() is False


# ==========================================
# R2 审查补充：在飞去重护栏 / webhook 拒绝分支 / 升级告警分支
# ==========================================
def test_kick_background_refresh_dedupes_inflight(monkeypatch):
    """在飞护栏：进行中的刷新期间，后续 kick 不得叠加新拉取（Q-M9-4 R2 P1-1）。"""
    import app.jobs.service as js

    js._refresh_inflight = False
    calls = []

    async def slow_pull():
        calls.append(1)
        await asyncio.sleep(0.05)
        return [{"record_id": "x"}]

    monkeypatch.setattr(js, "_pull_jobs_from_feishu", slow_pull)

    async def run():
        js._kick_background_refresh()
        js._kick_background_refresh()
        js._kick_background_refresh()
        await asyncio.sleep(0.25)

    asyncio.run(run())
    assert len(calls) == 1, f"在飞去重应只产生 1 次拉取，实际 {len(calls)}"
    assert js._refresh_inflight is False, "刷新结束后在飞标志必须复位"


def test_webhook_text_quick_approval_denied(monkeypatch):
    """webhook 通道文字门禁（与 WS 对称）：名单外「放行」→ 回执拒绝、不下发老 Agent。"""
    import app.api.routes.webhook as wh

    monkeypatch.setattr("app.core.config.settings.FEISHU_APPROVER_OPEN_IDS", "ou_boss", raising=False)
    sent = []
    # webhook 顶部 from-import 按值绑定，patch 必须打在 webhook 命名空间
    monkeypatch.setattr("app.api.routes.webhook.send_feishu_message",
                        lambda chat_id, text, *a, **k: sent.append(text))
    called = []
    monkeypatch.setattr(wh, "process_chatops_query", lambda *a, **k: called.append(1))
    monkeypatch.setattr("app.core.feishu_msg_dedup.check_and_mark", lambda mid: True)
    from app.services.chat_agent import agent as chat_agent
    monkeypatch.setattr(chat_agent, "is_ready", lambda: False)

    wh._process_webhook_event({
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "message": {
                "message_type": "text", "chat_id": "oc_chat1", "message_id": "om_wh_m9_1",
                "create_time": str(int(__import__("time").time() * 1000)),
                "content": __import__("json").dumps({"text": "放行"}, ensure_ascii=False),
            },
            "sender": {"sender_type": "user", "sender_id": {"open_id": "ou_mallory"}},
        },
    })
    assert called == [], "名单外不得下发老 Agent"
    assert any("审批权限" in t for t in sent)


def test_sync_loop_escalates_after_consecutive_unknowns(monkeypatch, tmp_path):
    """连续 5 个查重未知态 → 升级告警（🚨 + SSE error 通道）。"""
    import sqlite3

    from job_processor import step2_sync_feishu as s2

    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE jobs (company_name TEXT, job_title TEXT, city TEXT, "
                "job_link TEXT, process_status TEXT, is_synced INTEGER DEFAULT 0, "
                "feishu_record_id TEXT DEFAULT '')")
    for i in range(5):
        con.execute("INSERT INTO jobs (company_name, job_title, city, job_link, process_status) "
                    f"VALUES ('公司A','岗位{i}','广州','link{i}','待推送至飞书')")
    con.commit()
    con.close()

    monkeypatch.setattr(s2, "check_job_exists", lambda *a, **k: None)
    created = []
    monkeypatch.setattr(s2, "push_single_record_to_feishu", lambda *a, **k: created.append(1) or False)
    sse = []
    monkeypatch.setattr(s2, "push_sse_message_sync",
                        lambda task_id, message, status="info": sse.append((message, status)))

    s2.sync_sqlite_to_feishu(str(db), table_name="jobs")

    assert created == []
    errors = [m for m, st in sse if st == "error"]
    assert errors and "连续 5 个岗位查重未知态" in errors[0], f"应触发升级告警: {errors}"
