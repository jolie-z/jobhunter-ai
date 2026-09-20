"""P1 修复回归测试：老链路重试重复、评估链路静默死亡、物料假成功、确认生成丢修改稿。

对应 2026-09-02 ChatAgent 全链路质检 P1 项：
- feishu_service 发消息禁用网关重试（非幂等 POST 重试=重复投递）
- 评估进度卡首发失败不死链路 + 文字兜底 + 失败结局文字必达
- 物料发送失败不再假成功；未全部送达不标记「已送达」（防重启恢复永久跳过补发）
- _confirm_and_render 会话先渲染后 pop（渲染失败修改稿不丢）；文件发送如实汇报
"""
import asyncio

import pytest

from app.services import resume_edit_chat


# ==========================================
# P1-1: feishu_service 发消息禁用网关层重试
# ==========================================
def test_feishu_service_message_send_disables_gateway_retry(monkeypatch):
    """POST 发消息是非幂等操作，safe_feishu_request 必须 max_retries=1（禁重试防双发）。"""
    import app.services.feishu_service as fs

    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, "max_retries": kwargs.get("max_retries")})
        class _R:
            status_code = 200
            def json(self):
                return {"code": 0, "data": {"message_id": "om_x"}}
        return _R()

    def fake_token():
        return "tok_test"

    monkeypatch.setattr(fs, "safe_feishu_request", fake_request)
    monkeypatch.setattr(fs, "get_tenant_access_token", fake_token)
    # 本用例要验证 safe_feishu_request 层的 max_retries=1 契约，需放行守卫让调用落到桩上；
    # 仅本用例作用域生效，且 fake_request 全程拦截真实网络。
    monkeypatch.setattr(fs, "is_testing_env", lambda: False)

    fs.send_feishu_message("oc_test_retry", "重试测试")
    fs.send_feishu_card("oc_test_retry", {"header": {}})
    fs.send_feishu_file("oc_test_retry", "file_key_x")

    assert len(calls) == 3
    for c in calls:
        assert c["max_retries"] == 1, f"发消息类 POST 必须禁用网关重试（{c['url'][:60]}...）"


# ==========================================
# P1-2: 评估进度卡首发失败不死链路
# ==========================================
def test_pipeline_feedback_survives_progress_card_send_failure(monkeypatch):
    """进度卡首发抛异常时：链路继续、登记不中断、给用户文字兜底、失败结局也有文字通知。"""
    from app.services import eval_pipeline_feedback as epf
    from app.automation import inflight_registry

    texts, registered, unregistered = [], [], []

    async def fail_card(chat_id, card, receive_id_type="chat_id"):
        raise RuntimeError("feishu card send failed (simulated)")

    async def ok_text(receive_id, text, receive_id_type="chat_id"):
        texts.append(text)
        return True

    async def fake_fetch(table_id, record_id):
        return {"fields": {"公司名称": "评估公司", "岗位名称": "评估岗位"}}

    async def fake_pipeline(record_id, stop_at_review, on_node_done, resume):
        return {"outcome": "failed", "error": "评估超时"}

    monkeypatch.setattr("app.core.feishu_client.feishu_client.fetch_bitable_record_by_id", fake_fetch)
    monkeypatch.setattr(epf, "send_feishu_card", fail_card)
    monkeypatch.setattr(epf, "send_feishu_message", ok_text)
    monkeypatch.setattr("app.automation.full_auto.run_single_job_pipeline_async", fake_pipeline)
    monkeypatch.setattr(inflight_registry, "has", lambda rid: False)
    monkeypatch.setattr(inflight_registry, "get", lambda rid: None)
    monkeypatch.setattr(inflight_registry, "register", lambda rid, **kw: registered.append(rid))
    monkeypatch.setattr(inflight_registry, "mark_materials_delivered", lambda rid: None)
    monkeypatch.setattr(inflight_registry, "unregister", lambda rid: unregistered.append(rid))

    asyncio.run(epf._launch_single_job_pipeline("chat_p1_2", "recP1Test1"))

    assert registered == ["recP1Test1"], "即使进度卡发送失败，inflight 也必须登记（供重启恢复）"
    assert unregistered == ["recP1Test1"], "结束后必须注销登记"
    assert any("评估已启动" in t for t in texts), "进度卡失败必须文字兜底「已启动」，不能石沉大海"
    assert any("评估未完成" in t for t in texts), "失败结局必须有文字通知（不能只依赖进度卡 PATCH）"


# ==========================================
# P1-3: 物料发送失败不再假成功
# ==========================================
def _patch_materials_chain(monkeypatch, *, pdf_send_ok: bool, img_send_ok: bool, captured=None):
    from app.core import feishu_client as fcm
    from app.core import feishu_messaging as fm

    async def fake_fetch(table_id, record_id):
        return {"fields": {
            "公司名称": "物料公司", "岗位名称": "物料岗位",
            "PDF备份": [{"file_token": "tok_pdf"}],
            "图片保存": [{"file_token": "tok_img"}],
        }}

    def fake_download(token, save_path):
        with open(save_path, "wb") as f:
            f.write(b"x")
        return True

    async def fake_up_file(data, name):
        return f"fk_{name}"

    async def fake_up_img(data):
        return "ik_1"

    async def s_file(receive_id, file_key, receive_id_type="chat_id"):
        if captured is not None:
            captured.setdefault("files", []).append(file_key)
        return pdf_send_ok

    async def s_img(receive_id, image_key, receive_id_type="chat_id"):
        if captured is not None:
            captured.setdefault("images", []).append(image_key)
        return img_send_ok

    monkeypatch.setattr(fcm.feishu_client, "fetch_bitable_record_by_id", fake_fetch)
    monkeypatch.setattr("app.core.feishu_utils.download_feishu_file", fake_download)
    monkeypatch.setattr(fm, "upload_file_to_feishu", fake_up_file)
    monkeypatch.setattr(fm, "upload_image_to_feishu", fake_up_img)
    monkeypatch.setattr(fm, "send_feishu_file", s_file)
    monkeypatch.setattr(fm, "send_feishu_image", s_img)


def test_deliver_materials_returns_false_when_pdf_send_fails(monkeypatch):
    """PDF 发送失败：交付函数必须返回 False（不得标记已送达），汇总话术不出现该物料。"""
    from app.services import materials_delivery as md

    sent_texts = []

    async def fake_text(receive_id, text, receive_id_type="chat_id"):
        sent_texts.append(text)
        return True

    _patch_materials_chain(monkeypatch, pdf_send_ok=False, img_send_ok=True)
    monkeypatch.setattr(md, "send_feishu_message", fake_text)

    result = asyncio.run(md._deliver_materials_to_chat("chat_p1_3a", "recP1Mat1"))

    assert result is False, "关键物料（PDF）发送失败时必须返回 False"
    assert any("没找到可发送的物料" in t or "部分文件发送失败" in t or "已送达：简历长图" in t for t in sent_texts)
    assert not any("已送达：PDF 简历、简历长图" in t for t in sent_texts), "PDF 没发出去不得出现在送达清单里"


def test_deliver_materials_returns_true_when_all_delivered(monkeypatch):
    """PDF/长图全部真实送达：返回 True。"""
    from app.services import materials_delivery as md

    sent_texts = []

    async def fake_text(receive_id, text, receive_id_type="chat_id"):
        sent_texts.append(text)
        return True

    _patch_materials_chain(monkeypatch, pdf_send_ok=True, img_send_ok=True)
    monkeypatch.setattr(md, "send_feishu_message", fake_text)
    monkeypatch.setattr(md, "_generate_eval_report_image", lambda fields: b"")
    monkeypatch.setattr(md, "_ensure_eval_report_field", lambda: False)

    result = asyncio.run(md._deliver_materials_to_chat("chat_p1_3b", "recP1Mat2"))

    assert result is True, "全部关键物料送达时应返回 True（调用方据此标记已送达）"
    assert any("已送达：PDF 简历、简历长图" in t for t in sent_texts)


def test_mark_materials_delivered_only_on_success(monkeypatch):
    """交付失败时评估反馈链路不得调用 mark_materials_delivered（防恢复期永久跳过补发）。"""
    from app.services import eval_pipeline_feedback as epf
    from app.automation import inflight_registry

    marked = []

    async def ok_text(receive_id, text, receive_id_type="chat_id"):
        return True

    async def fake_deliver(chat_id, record_id, company="", job=""):
        return False  # 模拟物料部分发送失败

    async def fake_pipeline(record_id, stop_at_review, on_node_done, resume):
        return {"outcome": "stopped", "status": "简历人工复核"}

    async def fake_fetch(table_id, record_id):
        return {"fields": {"公司名称": "评估公司", "岗位名称": "评估岗位"}}

    monkeypatch.setattr("app.core.feishu_client.feishu_client.fetch_bitable_record_by_id", fake_fetch)
    monkeypatch.setattr(epf, "send_feishu_card", lambda *a, **kw: _async_ret("om_card_1"))
    monkeypatch.setattr(epf, "send_feishu_message", ok_text)
    monkeypatch.setattr(epf, "update_feishu_card", lambda *a, **kw: _async_ret(True))
    monkeypatch.setattr(epf, "_deliver_materials_to_chat", fake_deliver)
    monkeypatch.setattr(inflight_registry, "has", lambda rid: False)
    monkeypatch.setattr(inflight_registry, "get", lambda rid: {})
    monkeypatch.setattr(inflight_registry, "register", lambda rid, **kw: None)
    monkeypatch.setattr(inflight_registry, "mark_materials_delivered", lambda rid: marked.append(rid))
    monkeypatch.setattr(inflight_registry, "unregister", lambda rid: None)
    monkeypatch.setattr("app.automation.full_auto.run_single_job_pipeline_async", fake_pipeline)

    asyncio.run(epf._launch_single_job_pipeline("chat_p1_3c", "recP1Mat3"))

    assert marked == [], "物料未全部送达时绝不能标记「已送达」（否则重启恢复永久跳过补发）"


async def _async_ret(v):
    return v


# ==========================================
# P1-4/5: _confirm_and_render 会话先渲染后 pop + 发送如实汇报
# ==========================================
def _make_edit_session(monkeypatch, tmp_path, chat_id, record_id="recConfirmP1"):
    """把编辑会话 store 重定向到 tmp_path（不碰线上状态文件），写入并返回会话 dict。"""
    from app.services.job_entry_chat import _PendingStore

    monkeypatch.setattr(resume_edit_chat, "_edit_sessions",
                        _PendingStore(tmp_path / "pending_resume_edit.json", 24 * 3600))
    resume_edit_chat._set_edit_session(chat_id, {
        "record_id": record_id,
        "stage": "confirm",
        "updated": '{"summary": "改动后的内容"}',
        "orig": '{"summary": "原始内容"}',
    })
    return resume_edit_chat._get_edit_session(chat_id)


def test_confirm_render_keeps_session_on_render_failure(monkeypatch, tmp_path):
    """渲染失败：编辑会话必须保留（修改稿不丢），且提示可重试。"""
    from app.core import feishu_client as fcm

    sent = []

    async def fake_text(receive_id, text, receive_id_type="chat_id"):
        sent.append(text)
        return True

    async def fake_fetch(table_id, record_id):
        return {"fields": {"公司名称": "确认公司", "岗位名称": "确认岗位"}}

    async def fail_render(resume_dict, name):
        return None  # 渲染失败

    monkeypatch.setattr("app.automation.materials._render_custom_resume_materials", fail_render)
    monkeypatch.setattr(fcm.feishu_client, "fetch_bitable_record_by_id", fake_fetch)
    monkeypatch.setattr(resume_edit_chat, "send_feishu_message", fake_text)

    session = _make_edit_session(monkeypatch, tmp_path, "chat_p1_4")
    asyncio.run(resume_edit_chat._confirm_and_render("chat_p1_4", session))

    assert resume_edit_chat._get_edit_session("chat_p1_4") is not None, "渲染失败时编辑会话必须保留（用户修改稿不可丢）"
    assert any("仍保留" in t and "确认生成" in t for t in sent), "失败提示必须如实告知可重试"


def test_confirm_render_honest_report_on_send_failure(monkeypatch, tmp_path):
    """回写成功但聊天框文件发送失败：会话出栈（表已是新内容），但话术必须如实报告失败份数。"""
    from app.core import feishu_client as fcm
    from app.core import feishu_messaging as fm
    from app.core import feishu_utils

    sent, updated = [], []

    async def fake_text(receive_id, text, receive_id_type="chat_id"):
        sent.append(text)
        return True

    async def fake_fetch(table_id, record_id):
        return {"fields": {"公司名称": "确认公司", "岗位名称": "确认岗位"}}

    async def fake_update(table_id, record_id, fields):
        updated.append(record_id)
        return {"code": 0}

    async def fake_render(resume_dict, name):
        return {"pdf_token": "tok_p", "img_token": "tok_i", "name": name}

    def fake_download(token, save_path):
        with open(save_path, "wb") as f:
            f.write(b"x")
        return True

    async def fake_up_file(data, name):
        return "fk_pdf"

    async def fake_up_img(data):
        return "ik_img"

    async def fail_file(receive_id, file_key, receive_id_type="chat_id"):
        return False  # PDF 发送失败

    async def ok_img(receive_id, image_key, receive_id_type="chat_id"):
        return True

    monkeypatch.setattr("app.automation.materials._render_custom_resume_materials", fake_render)
    monkeypatch.setattr(fcm.feishu_client, "fetch_bitable_record_by_id", fake_fetch)
    monkeypatch.setattr(fcm.feishu_client, "update_record", fake_update)
    monkeypatch.setattr(feishu_utils, "download_feishu_file", fake_download)
    monkeypatch.setattr(fm, "upload_file_to_feishu", fake_up_file)
    monkeypatch.setattr(fm, "upload_image_to_feishu", fake_up_img)
    monkeypatch.setattr(fm, "send_feishu_file", fail_file)
    monkeypatch.setattr(fm, "send_feishu_image", ok_img)
    monkeypatch.setattr(resume_edit_chat, "send_feishu_message", fake_text)
    monkeypatch.setattr(resume_edit_chat, "send_feishu_image", ok_img)
    monkeypatch.setattr(resume_edit_chat, "send_feishu_file", fail_file)

    session = _make_edit_session(monkeypatch, tmp_path, "chat_p1_5")
    asyncio.run(resume_edit_chat._confirm_and_render("chat_p1_5", session))

    assert updated == ["recConfirmP1"], "渲染成功后应回写多维表格"
    assert resume_edit_chat._get_edit_session("chat_p1_5") is None, "回写成功后（不可回退点）会话应出栈"
    assert any("发送失败 1 份" in t for t in sent), "文件发送失败必须如实报告份数"
    assert not any(t.startswith("✅ 新版物料已生成并发送") for t in sent), "有失败时不得报「已发送」全量成功"
