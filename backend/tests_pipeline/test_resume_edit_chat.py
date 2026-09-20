"""自然语言改简历 + 已投递状态流转测试。

外部边界（LLM、飞书读写、物料渲染、文件下载上传）全部 Mock；
意图判定/会话状态/确认闭环/改动回显全量真实执行。
"""
import asyncio
import json

import pytest

from app.services import resume_edit_chat


V2_SAMPLE = {
    "personalInfo": {"name": ""},
    "summary": "资深AI产品经理，负责智能客服系统",
    "workExperience": [{
        "title": "智能客服训练师", "company": "某美妆集团", "years": "2019.07-2023.08",
        "description": ["- **负责**智能客服系统优化与问答模型搭建"],
    }],
    "personalProjects": [],
    "education": [],
    "additional": {"technicalSkills": [], "languages": [], "certificationsTraining": []},
}


@pytest.fixture(autouse=True)
def _reset_state():
    resume_edit_chat._edit_sessions.clear()
    resume_edit_chat._last_delivered.clear()
    yield
    resume_edit_chat._edit_sessions.clear()
    resume_edit_chat._last_delivered.clear()
    resume_edit_chat._EDIT_SESSION_PATH.unlink(missing_ok=True)
    resume_edit_chat._LAST_DELIVERED_PATH.unlink(missing_ok=True)


def test_intent_detection_requires_context():
    resume_edit_chat.record_delivered_context("chat_a", "recJob1")

    assert resume_edit_chat.should_intercept_delivered("chat_a", "帮我把状态改为已投递")
    assert resume_edit_chat.should_intercept_delivered("chat_a", "投递完成了")
    assert not resume_edit_chat.should_intercept_delivered("chat_none", "已投递")
    assert not resume_edit_chat.should_intercept_delivered("chat_a", "把总结改成更强势的版本")  # 修改指令不是投递

    assert resume_edit_chat.should_intercept_edit("chat_a", "把工作经历里负责客服改成主导客服AI化")
    assert resume_edit_chat.should_intercept_edit("chat_a", "调整一下个人总结的表述")
    # 无上下文也拦截：进入岗位定位流程（定位失败会明确告知，不再落给 Agent 瞎猜）
    assert resume_edit_chat.should_intercept_edit("chat_none", "把总结改成更强势的版本")
    assert not resume_edit_chat.should_intercept_edit("chat_a", "帮我跑下全链路")  # 无修改动词


def test_edit_instruction_applies_llm_and_asks_confirm(monkeypatch):
    resume_edit_chat.record_delivered_context("chat_edit", "recEdit1")
    edited = json.loads(json.dumps(V2_SAMPLE))
    edited["summary"] = "主导级AI产品专家，深耕智能客服"

    class _Msg:
        content = json.dumps(edited, ensure_ascii=False)

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    class _Completions:
        def create(self, **kw):
            return _Resp()

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    import common.config as cfg
    monkeypatch.setattr(cfg, "get_openai_client", lambda caller="": _Client())

    sent = []

    async def fake_send(receive_id, text, receive_id_type="chat_id", **kw):
        sent.append(text)
        return True

    from app.core import feishu_client as fcm
    monkeypatch.setattr(fcm.feishu_client, "update_record", lambda *a, **k: (_ for _ in ()).throw(AssertionError("未确认不应写飞书")))

    async def fake_fetch(table_id, record_id):
        return {"fields": {"AI改写JSON": json.dumps(V2_SAMPLE, ensure_ascii=False)}}

    monkeypatch.setattr(fcm.feishu_client, "fetch_bitable_record_by_id", fake_fetch)
    monkeypatch.setattr(resume_edit_chat, "send_feishu_message", fake_send)

    asyncio.run(resume_edit_chat.handle_edit_message("chat_edit", "把个人总结改成 主导级AI产品专家，深耕智能客服"))

    session = resume_edit_chat._get_edit_session("chat_edit")
    assert session and session["stage"] == "confirm"
    assert json.loads(session["updated"])["summary"] == "主导级AI产品专家，深耕智能客服"
    assert any("已按指令修改" in s and "个人总结" in s for s in sent), "应回显改动模块"


def test_confirm_generates_materials_and_updates_feishu(monkeypatch):
    resume_edit_chat.record_delivered_context("chat_c", "recConf1")
    resume_edit_chat._set_edit_session("chat_c", {
        "record_id": "recConf1", "stage": "confirm",
        "updated": json.dumps(V2_SAMPLE, ensure_ascii=False),
        "orig": json.dumps({**V2_SAMPLE, "summary": "旧总结"}, ensure_ascii=False),
    })

    updated_fields, sent, files, images = [], [], [], []

    class _Captured:
        def __init__(self):
            self.rendered = None

    cap = _Captured()

    async def fake_update(table_id, record_id, fields):
        updated_fields.append(fields)
        return {"code": 0}

    async def fake_fetch(table_id, record_id):
        return {"fields": {"公司名称": "确认公司", "岗位名称": "确认岗位"}}

    async def fake_render(resume_dict, name):
        cap.rendered = resume_dict
        return {"pdf_token": "tp", "img_token": "ti", "name": name}

    def fake_download(token, save_path):
        with open(save_path, "wb") as f:
            f.write(b"x")
        return True

    async def fake_up_file(data, name):
        return f"fk_{name}"

    async def fake_up_img(data):
        return "ik_1"

    async def fake_s_file(rid, key, receive_id_type="chat_id"):
        files.append(key)
        return True  # 新契约：发送函数返回真实成败

    async def fake_s_img(rid, key, receive_id_type="chat_id"):
        images.append(key)
        return True

    async def fake_send(rid, text, receive_id_type="chat_id", **kw):
        sent.append(text)
        return True

    from app.core import feishu_client as fcm
    from app.core import feishu_messaging as fm
    from app.core import feishu_utils
    from app.automation import materials

    monkeypatch.setattr(fcm.feishu_client, "update_record", fake_update)
    monkeypatch.setattr(fcm.feishu_client, "fetch_bitable_record_by_id", fake_fetch)
    monkeypatch.setattr(materials, "_render_custom_resume_materials", fake_render)
    monkeypatch.setattr(feishu_utils, "download_feishu_file", fake_download)
    monkeypatch.setattr(fm, "upload_file_to_feishu", fake_up_file)
    monkeypatch.setattr(fm, "upload_image_to_feishu", fake_up_img)
    monkeypatch.setattr(fm, "send_feishu_file", fake_s_file)
    monkeypatch.setattr(fm, "send_feishu_image", fake_s_img)
    monkeypatch.setattr(resume_edit_chat, "send_feishu_file", fake_s_file)
    monkeypatch.setattr(resume_edit_chat, "send_feishu_image", fake_s_img)
    monkeypatch.setattr(resume_edit_chat, "send_feishu_message", fake_send)

    asyncio.run(resume_edit_chat.handle_edit_message("chat_c", "确认生成"))

    assert len(updated_fields) == 1
    f = updated_fields[0]
    assert json.loads(f["AI改写JSON"])["summary"] == "资深AI产品经理，负责智能客服系统"
    assert f["PDF备份"][0]["name"].startswith("确认公司_确认岗位")
    assert "PDF备份" in f and "图片保存" in f, "新附件应回写"
    assert files == ["fk_确认公司_确认岗位.pdf"] and images == ["ik_1"]
    assert "chat_c" not in resume_edit_chat._edit_sessions, "确认后会话应清除"
    assert any("新版物料已生成" in s and "已投递" in s for s in sent), "完成后应引导标记已投递"


def test_iterative_edit_applies_on_updated_json(monkeypatch):
    resume_edit_chat.record_delivered_context("chat_iter", "recIter1")
    v1 = json.loads(json.dumps(V2_SAMPLE))
    v1["summary"] = "第一轮修改后的总结"
    resume_edit_chat._set_edit_session("chat_iter", {
        "record_id": "recIter1", "stage": "confirm",
        "updated": json.dumps(v1, ensure_ascii=False),
        "orig": json.dumps(V2_SAMPLE, ensure_ascii=False),
    })

    second = json.loads(json.dumps(v1))
    second["summary"] = "第一轮修改后的总结（已精简）"

    class _Msg:
        content = json.dumps(second, ensure_ascii=False)

    class _Resp:
        choices = [_Msg.__new__(_Msg)]

    class _R2:
        def __init__(self):
            m = type("M", (), {"content": json.dumps(second, ensure_ascii=False)})
            self.choices = [type("C", (), {"message": m()})]

    class _Completions:
        def create(self, **kw):
            return _R2()

    import common.config as cfg

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    return _R2()

    monkeypatch.setattr(cfg, "get_openai_client", lambda caller="": _Client())

    from app.core import feishu_client as fcm

    monkeypatch.setattr(fcm.feishu_client, "update_record", lambda *a, **k: (_ for _ in ()).throw(AssertionError("迭代阶段不应写飞书")))

    async def fake_send(rid, text, receive_id_type="chat_id", **kw):
        return True

    monkeypatch.setattr(resume_edit_chat, "send_feishu_message", fake_send)

    asyncio.run(resume_edit_chat.handle_edit_message("chat_iter", "再精简一下总结"))

    session = resume_edit_chat._get_edit_session("chat_iter")
    assert session, "迭代后应保持会话"
    assert json.loads(session["updated"])["summary"].endswith("（已精简）"), "迭代应基于上一轮结果"
    assert json.loads(session["orig"])["summary"] == "第一轮修改后的总结", "orig 为上一轮结果（对照展示基准）"


def test_cancel_discards_session(monkeypatch):
    resume_edit_chat.record_delivered_context("chat_cancel", "recC1")
    resume_edit_chat._set_edit_session("chat_cancel", {
        "record_id": "recC1", "stage": "confirm",
        "updated": json.dumps(V2_SAMPLE, ensure_ascii=False),
        "orig": json.dumps(V2_SAMPLE, ensure_ascii=False),
    })
    sent = []

    async def fake_send(rid, text, receive_id_type="chat_id", **kw):
        sent.append(text)
        return True

    from app.core import feishu_client as fcm
    fcm.feishu_client.update_record = lambda *a, **k: (_ for _ in ()).throw(AssertionError("取消不应写飞书"))

    monkeypatch.setattr(resume_edit_chat, "send_feishu_message", fake_send)

    asyncio.run(resume_edit_chat.handle_edit_message("chat_cancel", "取消修改"))

    assert "chat_cancel" not in resume_edit_chat._edit_sessions
    assert any("取消" in s for s in sent)


def test_mark_delivered_updates_status_and_date(monkeypatch):
    resume_edit_chat.record_delivered_context("chat_d", "recJob9")
    from app.core import feishu_client as fcm

    updates, sent = [], []

    async def fake_update(table_id, record_id, fields):
        updates.append((record_id, fields))
        return {"code": 0}

    async def fake_send(rid, text, receive_id_type="chat_id", **kw):
        sent.append(text)
        return True

    monkeypatch.setattr(fcm.feishu_client, "update_record", fake_update)
    monkeypatch.setattr(resume_edit_chat, "send_feishu_message", fake_send)

    asyncio.run(resume_edit_chat.handle_delivered_reply("chat_d", "帮我把状态改为已投递"))

    record_id, fields = updates[0]
    assert record_id == "recJob9", "应定位到最近交付岗位"
    assert fields["跟进状态"] == "已投递"
    assert "投递日期" in fields


def test_delivered_card_has_button():
    card = resume_edit_chat.build_delivered_card("recCard9")
    btn = card["elements"][-1]["actions"][0]
    assert btn["value"] == {"action": "mark_delivered", "record_id": "recCard9"}


def test_legacy_markdown_record_auto_upgraded(monkeypatch):
    """旧记录（markdown）编辑时现场升级为 V2 JSON 并回写字段，而非拒绝。"""
    import asyncio
    from app.core import feishu_client as fcm

    resume_edit_chat.record_delivered_context("chat_legacy", "recLegacy1")
    md = "## 💡 个人总结\n**AI系统架构**：交付5项AI产品"
    upgraded_writes = []

    async def fake_fetch(table_id, record_id):
        return {"fields": {"AI改写JSON": md, "公司名称": "旧格公司", "岗位名称": "旧格岗位"}}

    async def fake_update(table_id, record_id, fields):
        upgraded_writes.append(fields)
        return {"code": 0}

    def fake_parse(md_content):  # 生产代码为同步函数（经 to_thread 调用）
        return {**V2_SAMPLE, "summary": "从 markdown 解析的总结"}

    def fake_active_rid():
        return None

    class _Msg:
        content = json.dumps({**V2_SAMPLE, "summary": "从 markdown 解析的总结"}, ensure_ascii=False)

    class _Resp:
        choices = [type("C", (), {"message": _Msg()})]

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    return _Resp()

    import common.config as cfg
    monkeypatch.setattr(fcm.feishu_client, "fetch_bitable_record_by_id", fake_fetch)
    monkeypatch.setattr(fcm.feishu_client, "update_record", fake_update)
    monkeypatch.setattr("ai_agents.markdown_to_json.parse_markdown_to_json", fake_parse)
    monkeypatch.setattr("app.services.feishu_service.get_active_resume_record_id", fake_active_rid)
    monkeypatch.setattr(cfg, "get_openai_client", lambda caller="": _Client())
    monkeypatch.setattr(resume_edit_chat, "send_feishu_message", lambda rid, text, receive_id_type="chat_id", **kw: asyncio.sleep(0, result=True))

    asyncio.run(resume_edit_chat.handle_edit_message("chat_legacy", "把个人总结再强化一下"))

    assert upgraded_writes, "升级后的 V2 JSON 应回写字段"
    assert json.loads(upgraded_writes[0]["AI改写JSON"])["summary"] == "从 markdown 解析的总结"
    session = resume_edit_chat._get_edit_session("chat_legacy")
    assert session and session["stage"] == "confirm"


# ==========================================
# 岗位定位（公司名+岗位名自然语言 → 候选）
# ==========================================
JOBS_FIXTURE = [
    {"record_id": "recA", "company_name": "唯品会（中国）有限公司", "job_name": "AI产品运营（客服方向）"},
    {"record_id": "recB", "company_name": "唯品会（中国）有限公司", "job_name": "电商运营经理"},
    {"record_id": "recC", "company_name": "字节跳动", "job_name": "后端开发工程师"},
]


def _mock_jobs(monkeypatch):
    from app.jobs import service as jobs_service

    async def fake_jobs(force=False):
        return [dict(j) for j in JOBS_FIXTURE]

    monkeypatch.setattr(jobs_service, "fetch_and_clean_all_jobs", fake_jobs)


def test_find_candidates_scoring(monkeypatch):
    from app.jobs import service as js

    async def fake_jobs(force=False):
        return [dict(j) for j in JOBS_FIXTURE]

    monkeypatch.setattr(js, "fetch_and_clean_all_jobs", fake_jobs)

    cands = asyncio.run(resume_edit_chat.find_job_candidates(
        "岗位是 唯品会（中国）有限公司 AI产品运营（客服方向），你能找到这个岗位吗"))

    assert cands, "应至少命中唯品会 AI产品运营"
    assert cands[0]["record_id"] == "recA", "最高分应为完整匹配的岗位"
    assert cands[0]["score"] == 1.0
    assert all(c["record_id"] != "recC" for c in cands), "字节跳动不应入候选"


def test_find_candidates_no_match():
    import asyncio
    from app.jobs import service as js

    async def fake_jobs(force=False):
        return [dict(j) for j in JOBS_FIXTURE]

    orig = js.fetch_and_clean_all_jobs
    js.fetch_and_clean_all_jobs = fake_jobs
    try:
        cands = asyncio.run(resume_edit_chat.find_job_candidates("深圳市大数据研究院 算法实习生"))
    finally:
        js.fetch_and_clean_all_jobs = orig
    assert cands == []


def test_locate_single_match_binds_context(monkeypatch):
    import asyncio
    from app.jobs import service as js

    async def fake_jobs(force=False):
        return [dict(j) for j in [JOBS_FIXTURE[0]]]  # 只有唯品会AI产品运营一条

    monkeypatch.setattr(js, "fetch_and_clean_all_jobs", fake_jobs)
    sent = []

    async def fake_send(rid, text, receive_id_type="chat_id", **kw):
        sent.append(text)
        return True

    monkeypatch.setattr(resume_edit_chat, "send_feishu_message", fake_send)
    # 卡片幂等降级 helper 直连 feishu_messaging：卡片必失败时桩也必须打到源头
    async def fail_card(rid, card, receive_id_type="chat_id", **kw):
        raise RuntimeError("card send failed (simulated)")

    from app.core import feishu_messaging as _fm
    monkeypatch.setattr(_fm, "send_feishu_card", fail_card)
    monkeypatch.setattr(_fm, "send_feishu_message", fake_send)

    asyncio.run(resume_edit_chat.handle_locate("chat_loc1", "岗位是 唯品会（中国）有限公司 AI产品运营（客服方向），你能找到这个岗位吗"))

    assert resume_edit_chat._read_ptr(resume_edit_chat._edit_target, "chat_loc1")[0] == "recA", "显式定位应绑定编辑目标指针"
    assert any("已定位岗位" in s for s in sent)


def test_locate_multi_match_shows_candidates(monkeypatch):
    import asyncio
    from app.jobs import service as js

    async def fake_jobs(force=False):
        return [dict(j) for j in JOBS_FIXTURE]  # 唯品会两条 → 公司名命中2个

    monkeypatch.setattr(js, "fetch_and_clean_all_jobs", fake_jobs)
    cards, sent = [], []

    async def fake_card(rid, card, receive_id_type="chat_id"):
        cards.append(card)
        return None

    async def fake_send(rid, text, receive_id_type="chat_id", **kw):
        sent.append(text)
        return True

    monkeypatch.setattr(resume_edit_chat, "send_feishu_card", fake_card)
    monkeypatch.setattr(resume_edit_chat, "send_feishu_message", fake_send)

    asyncio.run(resume_edit_chat.handle_locate("chat_loc2", "找岗位 唯品会"))

    assert len(cards) == 1
    div_elements = [el for el in cards[0]["elements"] if el.get("tag") == "div"]
    assert {el["extra"]["value"]["record_id"] for el in div_elements} == {"recA", "recB"}, "唯品会两个岗位都应入候选"
    assert resume_edit_chat._pending_locate.get("chat_loc2"), "多命中应存候选待点选"


def test_locate_zero_match_replies_miss(monkeypatch):
    import asyncio
    from app.jobs import service as js

    async def fake_jobs(force=False):
        return [dict(j) for j in JOBS_FIXTURE]

    monkeypatch.setattr(js, "fetch_and_clean_all_jobs", fake_jobs)
    sent = []

    async def fake_send(rid, text, receive_id_type="chat_id", **kw):
        sent.append(text)
        return True

    monkeypatch.setattr(resume_edit_chat, "send_feishu_message", fake_send)

    asyncio.run(resume_edit_chat.handle_locate("chat_loc3", "岗位是 深圳大数据研究院 算法实习生"))

    assert any("没有在岗位表找到" in s for s in sent)


def test_candidate_selected_applies_pending_instruction(monkeypatch):
    resume_edit_chat._pending_locate["chat_pick"] = json.dumps(
        {"candidates": [{"record_id": "recPick", "company": "唯品会", "title": "AI产品运营", "score": 1.0}],
         "instruction": "把个人总结改成 深耕零售AI"},
        ensure_ascii=False,
    )

    edited = json.loads(json.dumps(V2_SAMPLE))
    edited["summary"] = "深耕零售AI"

    class _Msg:
        content = json.dumps(edited, ensure_ascii=False)

    class _Resp:
        choices = [type("C", (), {"message": _Msg()})]

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    return _Resp()

    from app.core import feishu_client as fcm
    import common.config as cfg

    async def fake_fetch(table_id, record_id):
        return {"fields": {"AI改写JSON": json.dumps(V2_SAMPLE, ensure_ascii=False), "公司名称": "唯品会", "岗位名称": "AI产品运营"}}

    async def fake_rid():
        return None

    monkeypatch.setattr(fcm.feishu_client, "fetch_bitable_record_by_id", fake_fetch)
    monkeypatch.setattr(fcm.feishu_client, "update_record", lambda *a, **k: (_ for _ in ()).throw(AssertionError("未确认不应写飞书")))
    monkeypatch.setattr("ai_agents.markdown_to_json.parse_markdown_to_json", lambda md: dict(V2_SAMPLE))
    monkeypatch.setattr("app.services.feishu_service.get_active_resume_record_id", fake_rid)
    monkeypatch.setattr(cfg, "get_openai_client", lambda caller="": _Client())
    monkeypatch.setattr(resume_edit_chat, "send_feishu_message", lambda rid, text, receive_id_type="chat_id", **kw: asyncio.sleep(0, result=True))

    asyncio.run(resume_edit_chat.handle_candidate_selected("chat_pick", "recPick"))

    assert resume_edit_chat._read_ptr(resume_edit_chat._edit_target, "chat_pick")[0] == "recPick", "点选绑定应写编辑目标指针（不污染交付锚点）"
    assert resume_edit_chat._read_ptr(resume_edit_chat._last_delivered, "chat_pick")[0] == "", "点选不应覆盖最近交付锚点"
    session = resume_edit_chat._get_edit_session("chat_pick")
    assert session and json.loads(session["updated"])["summary"] == "深耕零售AI", "点选后应立即执行待执行的修改指令"
    assert "chat_pick" not in resume_edit_chat._pending_locate


def test_edit_without_context_single_hit_asks_card_then_executes(monkeypatch):
    """无上下文的修改指令 → 单命中也不直连（防误定位）：先推候选卡反问，点选后立即执行。"""
    import asyncio
    from app.jobs import service as js
    from app.core import feishu_client as fcm
    import common.config as cfg

    async def fake_jobs(force=False):
        return [dict(j) for j in [JOBS_FIXTURE[0]]]

    monkeypatch.setattr(js, "fetch_and_clean_all_jobs", fake_jobs)

    edited = json.loads(json.dumps(V2_SAMPLE))
    edited["summary"] = "按指令修改后的总结"

    class _Msg:
        content = json.dumps(edited, ensure_ascii=False)

    class _Resp:
        choices = [type("C", (), {"message": _Msg()})]

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    return _Resp()

    async def fake_fetch(table_id, record_id):
        return {"fields": {"AI改写JSON": json.dumps(V2_SAMPLE, ensure_ascii=False), "公司名称": "唯品会（中国）有限公司", "岗位名称": "AI产品运营（客服方向）"}}

    async def fake_rid():
        return None

    monkeypatch.setattr(fcm.feishu_client, "fetch_bitable_record_by_id", fake_fetch)
    monkeypatch.setattr(fcm.feishu_client, "update_record", lambda *a, **k: (_ for _ in ()).throw(AssertionError("未确认不应写飞书")))
    monkeypatch.setattr("app.services.feishu_service.get_active_resume_record_id", fake_rid)
    monkeypatch.setattr(cfg, "get_openai_client", lambda caller="": _Client())

    sent, cards = [], []

    async def fake_send(rid, text, receive_id_type="chat_id", **kw):
        sent.append(text)
        return True

    async def fake_card(rid, card, receive_id_type="chat_id"):
        cards.append(card)
        return "om_card_x"

    monkeypatch.setattr(resume_edit_chat, "send_feishu_message", fake_send)
    monkeypatch.setattr(resume_edit_chat, "send_feishu_card", fake_card)

    asyncio.run(resume_edit_chat.handle_edit_message("chat_noctx", "把唯品会 AI产品运营 的个人总结改成 按指令修改后的总结"))

    # 反问确认：单命中也发候选卡，不直接执行
    assert cards, "单命中应发候选卡反问"
    assert resume_edit_chat._pending_locate.get("chat_noctx"), "候选与指令应存待点选"
    assert not resume_edit_chat._get_edit_session("chat_noctx"), "确认前不应执行修改"
    assert any("您要修改哪个岗位" in s for s in sent)

    # 点选确认 → 立即执行
    asyncio.run(resume_edit_chat.handle_candidate_selected("chat_noctx", "recA"))

    assert resume_edit_chat._read_ptr(resume_edit_chat._edit_target, "chat_noctx")[0] == "recA", "点选后绑定编辑目标"
    session = resume_edit_chat._get_edit_session("chat_noctx")
    assert session and json.loads(session["updated"])["summary"] == "按指令修改后的总结"


def test_weak_false_positive_filtered_by_relative_cutoff():
    """完全匹配存在时，模糊凑分的其他公司（如 DeepSeek 误命中）应被剔除。"""
    import asyncio
    from app.jobs import service as js

    jobs = [
        {"record_id": "recA1", "company_name": "唯品会（中国）有限公司", "job_name": "AI产品运营（客服方向）", "follow_status": "简历人工复核"},
        {"record_id": "recA2", "company_name": "唯品会（中国）有限公司", "job_name": "AI产品运营（客服方向）", "follow_status": "新线索"},
        {"record_id": "recDS", "company_name": "DeepSeek", "job_name": "DeepSeek AI岗位招聘", "follow_status": "新线索"},
    ]

    async def fake_jobs(force=False):
        return [dict(j) for j in jobs]

    monkeypatch = type("M", (), {"setattr": staticmethod(lambda o, n, v: setattr(o, n, v))})
    orig = js.fetch_and_clean_all_jobs
    js.fetch_and_clean_all_jobs = fake_jobs
    try:
        cands = asyncio.run(resume_edit_chat.find_job_candidates(
            "帮我把 岗位是 唯品会（中国）有限公司 AI产品运营（客服方向） 的 简历内容进行修改"))
    finally:
        js.fetch_and_clean_all_jobs = orig

    ids = [c["record_id"] for c in cands]
    assert "recDS" not in ids, "相对截断应剔除模糊误命中"
    assert set(ids) == {"recA1", "recA2"}
    assert all(c["status"] for c in cands), "候选应携带跟进状态"


def test_candidates_card_buttons_carry_status():
    card = resume_edit_chat.build_candidates_card([
        {"record_id": "recS1", "company": "唯品会", "title": "AI产品运营（客服方向）", "status": "简历人工复核", "salary": "25-35K", "city": "广州"},
        {"record_id": "recS2", "company": "唯品会", "title": "AI产品运营（客服方向）", "status": "新线索", "salary": "20-30K", "city": "深圳"},
    ])
    # 结构化卡片：第0项为 candidate 1, 第1项为 hr, 第2项为 candidate 2, 第3项为 note
    elem0 = card["elements"][0]
    elem2 = card["elements"][2]
    assert "人工复核" in elem0["text"]["content"] and "25-35K" in elem0["text"]["content"], "同名岗位应靠跟进状态和薪资地点区分"
    assert elem0["extra"]["value"]["record_id"] == "recS1"
    assert "新线索" in elem2["text"]["content"] and "深圳" in elem2["text"]["content"]
    assert elem2["extra"]["value"]["record_id"] == "recS2"
    assert card["elements"][-1]["tag"] == "note"


# ==========================================
# 品牌词负信号（真实事故回归：deepseek 模型名曾被当 DeepSeek 公司命中）
# ==========================================
def test_brand_words_not_company_signal(monkeypatch):
    """列举模型名（GPT/claude/deepseek/qwen/glm）不应把 DeepSeek 公司命中为定位候选。"""
    import asyncio
    from app.jobs import service as js

    jobs = [dict(j) for j in JOBS_FIXTURE] + [
        {"record_id": "recDS", "company_name": "DeepSeek", "job_name": "DeepSeek AI岗位招聘", "follow_status": "新线索"},
    ]

    async def fake_jobs(force=False):
        return [dict(j) for j in jobs]

    monkeypatch.setattr(js, "fetch_and_clean_all_jobs", fake_jobs)

    cands = asyncio.run(resume_edit_chat.find_job_candidates(
        "帮我修改一下简历内容：个人总结模块的 具备基于大模型（GPT）改为 具备基于大模型（GPT/claude/deepseek/qwen/glm）"))

    assert all(c["record_id"] != "recDS" for c in cands), "模型列举中的品牌词不应命中同名公司"


def test_brand_word_with_company_context_still_matches(monkeypatch):
    """品牌词紧跟求职语境词（deepseek公司）时保留，仍可定位同名公司岗位。"""
    import asyncio
    from app.jobs import service as js

    jobs = [{"record_id": "recDS", "company_name": "DeepSeek", "job_name": "DeepSeek AI岗位招聘", "follow_status": "新线索"}]

    async def fake_jobs(force=False):
        return [dict(j) for j in jobs]

    monkeypatch.setattr(js, "fetch_and_clean_all_jobs", fake_jobs)

    cands = asyncio.run(resume_edit_chat.find_job_candidates("把 DeepSeek公司 的岗位jd 改成 强调多模型经验"))

    assert any(c["record_id"] == "recDS" for c in cands), "指名公司时应正常命中"


def test_resolve_context_target_prefers_newer_pointer():
    """编辑目标与交付锚点双指针：最近一次意图优先。"""
    resume_edit_chat.record_delivered_context("chat_ptr", "recDelivered")
    resume_edit_chat.record_edit_target("chat_ptr", "recTarget")
    assert resume_edit_chat._resolve_context_target("chat_ptr") == "recTarget"

    resume_edit_chat.record_delivered_context("chat_ptr", "recDelivered2")
    assert resume_edit_chat._resolve_context_target("chat_ptr") == "recDelivered2", "更新的交付应成为当前目标"


def test_anchor_mismatch_asks_confirm_then_execute(monkeypatch):
    """上下文岗位的简历里找不到指令引用的原文 → 反问确认；「确认」后按当前岗位执行。"""
    import asyncio
    from app.core import feishu_client as fcm
    import common.config as cfg

    resume_edit_chat.record_delivered_context("chat_anchor", "recAnchor")

    edited = json.loads(json.dumps(V2_SAMPLE))
    edited["summary"] = "按确认执行的总结"

    class _Msg:
        content = json.dumps(edited, ensure_ascii=False)

    class _Resp:
        choices = [type("C", (), {"message": _Msg()})]

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    return _Resp()

    async def fake_fetch(table_id, record_id):
        return {"fields": {"AI改写JSON": json.dumps(V2_SAMPLE, ensure_ascii=False), "公司名称": "唯品会", "岗位名称": "AI产品运营"}}

    async def fake_rid():
        return None

    monkeypatch.setattr(fcm.feishu_client, "fetch_bitable_record_by_id", fake_fetch)
    monkeypatch.setattr(fcm.feishu_client, "update_record", lambda *a, **k: (_ for _ in ()).throw(AssertionError("未确认不应写飞书")))
    monkeypatch.setattr("app.services.feishu_service.get_active_resume_record_id", fake_rid)
    monkeypatch.setattr(cfg, "get_openai_client", lambda caller="": _Client())

    sent = []

    async def fake_send(rid, text, receive_id_type="chat_id", **kw):
        sent.append(text)
        return True

    monkeypatch.setattr(resume_edit_chat, "send_feishu_message", fake_send)

    # 原文锚点（量子区块链跨链协议）不在 V2_SAMPLE 里 → 反问
    asyncio.run(resume_edit_chat.handle_edit_message(
        "chat_anchor", "把 量子区块链模块的跨链协议 改成 轻节点验证"))

    assert any("没找到你要改的原文" in s for s in sent), "锚点对不上应反问确认"
    assert resume_edit_chat._pending_target_confirm.get("chat_anchor"), "待确认状态应落盘"
    assert not resume_edit_chat._get_edit_session("chat_anchor"), "确认前不应执行修改"

    # 「确认」→ 按当前岗位执行
    asyncio.run(resume_edit_chat.handle_edit_message("chat_anchor", "确认"))

    assert not resume_edit_chat._pending_target_confirm.get("chat_anchor"), "确认后待确认状态应清除"
    session = resume_edit_chat._get_edit_session("chat_anchor")
    assert session and json.loads(session["updated"])["summary"] == "按确认执行的总结"


def test_anchor_match_edits_directly(monkeypatch):
    """指令引用的原文能在上下文简历里找到 → 一致性校验通过，直接执行不反问。"""
    import asyncio
    from app.core import feishu_client as fcm
    import common.config as cfg

    resume = json.loads(json.dumps(V2_SAMPLE))
    resume["summary"] = "具备基于大模型（GPT）的智能客服系统实战经验"
    resume_edit_chat.record_delivered_context("chat_hit", "recHit")

    edited = json.loads(json.dumps(resume))
    edited["summary"] = "具备基于大模型（GPT/claude/deepseek/qwen/glm）的智能客服系统实战经验"

    class _Msg:
        content = json.dumps(edited, ensure_ascii=False)

    class _Resp:
        choices = [type("C", (), {"message": _Msg()})]

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    return _Resp()

    async def fake_fetch(table_id, record_id):
        return {"fields": {"AI改写JSON": json.dumps(resume, ensure_ascii=False), "公司名称": "唯品会", "岗位名称": "AI产品运营"}}

    async def fake_rid():
        return None

    monkeypatch.setattr(fcm.feishu_client, "fetch_bitable_record_by_id", fake_fetch)
    monkeypatch.setattr(fcm.feishu_client, "update_record", lambda *a, **k: (_ for _ in ()).throw(AssertionError("确认生成前不应写飞书")))
    monkeypatch.setattr("app.services.feishu_service.get_active_resume_record_id", fake_rid)
    monkeypatch.setattr(cfg, "get_openai_client", lambda caller="": _Client())
    monkeypatch.setattr(resume_edit_chat, "send_feishu_message",
                        lambda rid, text, receive_id_type="chat_id", **kw: asyncio.sleep(0, result=True))

    asyncio.run(resume_edit_chat.handle_edit_message(
        "chat_hit", "把 具备基于大模型（GPT） 改为 具备基于大模型（GPT/claude/deepseek/qwen/glm）"))

    assert not resume_edit_chat._pending_target_confirm.get("chat_hit"), "锚点匹配不应反问"
    session = resume_edit_chat._get_edit_session("chat_hit")
    assert session and "claude" in json.loads(session["updated"])["summary"], "锚点匹配应直接进入修改"
