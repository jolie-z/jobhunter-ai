import os
import sys
from pathlib import Path

from app.automation.failure_triage import classify_delivery_failure
from app.automation.snapshot_service import build_failure_job, build_failure_suggestion
from app.automation.tools import _format_delivery_error


def test_format_delivery_error_preserves_detail():
    # 验证真实错误能被原汁原味透传，且不带有“引擎执行失败”的误杀前缀
    job_data = {"delivery_error": "[附件未送达] 发送浮层中未出现目标简历「我的简历」，中止发送以防发错简历"}
    msg = _format_delivery_error("猎聘", job_data)
    assert "❌ 猎聘投递受阻：[附件未送达]" in msg
    assert "引擎执行失败" not in msg


def test_format_delivery_error_fallback():
    # 无 detail 时兜底
    msg = _format_delivery_error("BOSS直聘", {})
    assert "❌ BOSS直聘投递受阻，请检查相关日志" == msg


def test_failure_triage_attachment_not_delivered_is_transient():
    # 验证 [附件未送达] 被精确归类为暂时性故障，不被当成持久性故障阻断重试
    err = "❌ 猎聘投递受阻：[附件未送达] 发送浮层中未出现目标简历「我的简历」，中止发送以防发错简历"
    kind = classify_delivery_failure(err)
    assert kind == "transient"


def test_failure_triage_chat_blocked_is_transient():
    err = "❌ 智联招聘投递受阻：[微聊受阻] 附件简历已成功送达，打招呼语未成功发送"
    kind = classify_delivery_failure(err)
    assert kind == "transient"


def test_workflow_success_check_strict_prefix():
    # 验证升级后的严格前缀判断，杜绝子串匹配地雷
    success_msg = "✅ 猎聘投递引擎执行成功"
    assert success_msg.startswith("✅") and "微聊受阻" not in success_msg

    # 包含“成功”字样但以 ❌ 开头的失败消息绝不会被误判为成功
    fail_with_word = "❌ 猎聘投递受阻：打招呼语发送成功，但附件未送达"
    assert not (fail_with_word.startswith("✅") and "微聊受阻" not in fail_with_word)


def test_snapshot_suggestion_matrix_matches_structured_tags():
    assert "单独补发附件简历" in build_failure_suggestion("❌ 猎聘投递受阻：[附件未送达] 发送浮层未匹配")
    assert "单独补发专属打招呼语" in build_failure_suggestion(
        "❌ 智联招聘投递受阻：[微聊受阻] 附件简历已成功送达，打招呼语未成功发送"
    )
    assert "放弃" in build_failure_suggestion("❌ BOSS直聘投递受阻：[下架] 岗位已下线")
    assert "检查简历附件" in build_failure_suggestion("❌ 51job投递受阻：[物料] 缺少岗位链接")
    assert "重新扫码登录" in build_failure_suggestion("❌ 猎聘投递受阻：[登录] 登录态失效")


def test_snapshot_suggestion_structured_tag_beats_free_keyword():
    # 「[物料] 打招呼语为非法内容」含"打招呼"，物料标签必须优先，不能误导向补发打招呼
    s = build_failure_suggestion("[物料] 打招呼语为非法内容（疑似生成失败的错误文本），已拦截")
    assert "检查简历附件" in s
    assert "补发" not in s
    # 无结构化标签的自由文本命中"打招呼"，不得断言"附件简历已成功送达"
    s2 = build_failure_suggestion("❌ 猎聘投递受阻：投递异常中断：打招呼输入框未出现")
    assert "附件简历已成功送达" not in s2
    assert "重试" in s2


def test_snapshot_suggestion_timeout_not_mapped_to_login():
    s = build_failure_suggestion("❌ 猎聘投递受阻：等待聊天框浮出超时")
    assert "扫码登录" not in s
    assert "重试" in s


def test_snapshot_failure_job_exposes_real_reason():
    # 回归守卫：failure_info.reason 缺失时前端会回退成固定文案，等于把真实原因再次抹平
    real_error = "❌ 猎聘投递受阻：[附件未送达] 发送浮层中未出现目标简历「我的简历」，中止发送以防发错简历"
    fval = {
        "error": real_error,
        "failed_at": "2026-09-15 23:13:22",
        "job_name": "AI产品经理-广州",
        "company_name": "某武汉互联网公司",
        "platform": "liepin",
        "grade": "C",
        "failure_count": 1,
    }
    job = build_failure_job("recvvfm80rujR1", fval, is_current_run=True, crawl_time="2026-09-15 20:00:00")
    info = job["failure_info"]
    assert info["reason"] == real_error
    assert "单独补发附件简历" in info["suggestion"]
    assert info["triage"] == "transient"
    assert "暂时性故障" in info["triage_note"]
    assert job["job_id"] == "recvvfm80rujR1"
    assert job["status"] == "error"
    assert job["platform"] == "liepin"
    assert job["last_action_time"] == "2026-09-15 23:13:22"


def _load_liepin_engine():
    liepin_dir = str(Path(__file__).resolve().parent.parent / "liepin_scraper")
    if liepin_dir not in sys.path:
        sys.path.insert(0, liepin_dir)
    import liepin_auto_delivery
    import liepin_im_sender
    return liepin_auto_delivery, liepin_im_sender


def _patch_liepin_engine(monkeypatch, engine, im_sender, *, open_chat, send_chat, send_resume) -> dict:
    """跳过登录/下载/上传，只让聊天与发简历三步可控；返回捕获的飞书回写字段。"""
    feishu_updates: dict = {}
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(engine, "ensure_login", lambda wait_s=0: True)
    monkeypatch.setattr(engine, "_manage_and_upload_resume", lambda *a, **k: None)
    monkeypatch.setattr(engine, "update_feishu_record", lambda r_id, fields: feishu_updates.update(fields))
    monkeypatch.setattr(im_sender, "_open_chat_box", open_chat)
    monkeypatch.setattr(im_sender, "_send_chat_message", send_chat)
    monkeypatch.setattr(im_sender, "_send_resume_in_chat", send_resume)
    return feishu_updates


def test_liepin_delivery_error_full_text_and_greeting_sent_tracking(monkeypatch):
    # 验证猎聘引擎在打招呼后发生异常时，delivery_error 完整保留且显式记录 greeting_sent
    engine, im_sender = _load_liepin_engine()
    long_error_detail = "x" * 200  # 超过 120 字的长异常

    def _raise_tagged(*_a, **_k):
        raise RuntimeError(f"[附件未送达] {long_error_detail}")

    feishu_updates = _patch_liepin_engine(
        monkeypatch, engine, im_sender,
        open_chat=lambda *a: "mock_box", send_chat=lambda *a: None, send_resume=_raise_tagged,
    )
    job_data = {"job_url": "https://www.liepin.com/job/123", "greeting": "您好，期望沟通", "record_id": "rec_test_123"}

    ok = engine.deliver_job(job_data)
    assert ok is False
    assert job_data.get("greeting_sent") is True
    # delivery_error 完整保留未截断原文；飞书失败日志实施 120 字截断
    assert len(job_data.get("delivery_error", "")) > 120
    assert long_error_detail in job_data.get("delivery_error", "")
    assert len(feishu_updates.get("自动投递失败日志", "")) <= 120
    # 引擎抛出时已带标签，不得重复拼接
    assert job_data["delivery_error"].count("[附件未送达]") == 1


def test_liepin_tags_attachment_stage_failure_after_greeting(monkeypatch):
    # 「未找到发简历图标」这类未带标签的附件阶段异常，打招呼已送达时必须补 [附件未送达]
    engine, im_sender = _load_liepin_engine()

    def _raise_untagged(*_a, **_k):
        raise RuntimeError("未找到聊天框顶部的「发简历」图标")

    feishu_updates = _patch_liepin_engine(
        monkeypatch, engine, im_sender,
        open_chat=lambda *a: "mock_box", send_chat=lambda *a: None, send_resume=_raise_untagged,
    )
    job_data = {"job_url": "https://www.liepin.com/job/123", "greeting": "您好", "record_id": "rec_test_456"}

    assert engine.deliver_job(job_data) is False
    assert job_data["greeting_sent"] is True
    assert job_data["delivery_error"].startswith("[附件未送达] 未找到聊天框顶部")
    assert "[附件未送达]" in feishu_updates["自动投递失败日志"]
    assert classify_delivery_failure(_format_delivery_error("猎聘", job_data)) == "transient"


def test_liepin_no_attachment_tag_when_greeting_not_sent(monkeypatch):
    # 打招呼之前就失败（聊天窗都没打开），附件与打招呼都未送达，绝不能标成 [附件未送达]
    engine, im_sender = _load_liepin_engine()

    def _raise_open_chat(*_a, **_k):
        raise RuntimeError("未找到「聊一聊/继续聊」按钮，可能岗位已下架")

    _patch_liepin_engine(
        monkeypatch, engine, im_sender,
        open_chat=_raise_open_chat, send_chat=lambda *a: None, send_resume=lambda *a, **k: None,
    )
    job_data = {"job_url": "https://www.liepin.com/job/123", "greeting": "您好", "record_id": "rec_test_789"}

    assert engine.deliver_job(job_data) is False
    assert job_data["greeting_sent"] is False
    assert "[附件未送达]" not in job_data["delivery_error"]
    assert "聊一聊/继续聊" in job_data["delivery_error"]
