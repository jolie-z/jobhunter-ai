# -*- coding: utf-8 -*-
"""桩测试：验证 51job 海投「我的简历」每日一次上传、当日复用的会话策略。

背景：旧「每岗位清空重传」策略会迅速耗尽 51job 每日上传配额（status=720721），
导致后续岗位附件上传静默失败、雇主只收到在线简历。本测试锁定「当日一次上传、
全程复用」行为，防止回退。

2026-09-16 起复用凭据从进程内存标志改为 upload_quota.mass_resume_date（当日新鲜度，
跨批次/跨进程有效）；reset_mass_apply_session() 语义为「下一海投岗强制重传最新母本」。
"""
import importlib
import os
import sys

os.environ["no_proxy"] = "*"; os.environ["NO_PROXY"] = "*"
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BACKEND_DIR, "51job_scraper"))

from app.automation import upload_quota

m = importlib.import_module("51job_auto_delivery")


class _FakePage:
    url = "https://www.51job.com/job/123.html"
    def goto(self, *a, **k): pass
    def reload(self, *a, **k): pass
    def route(self, *a, **k): pass
    def title(self): return "测试岗位"
    def locator(self, sel): return self
    def count(self): return 0
    def evaluate(self, js):
        if "applyJobFun" in js and "directApply" in js:
            return {"ok": False, "err": "already applied", "isApply": True}  # 提前终止
        return {"ok": True}
    def wait_for_load_state(self, *a, **k): pass


class _FakeCtx:
    def new_page(self): return _FakePage()


def _install_stubs(monkeypatch, calls, attach_list):
    monkeypatch.setattr(m, "_connect_browser", lambda p: (object(), _FakeCtx()))
    monkeypatch.setattr(m, "_close_popups", lambda page: None)
    monkeypatch.setattr(m, "_extract_job_info_from_page", lambda page: ("", ""))
    monkeypatch.setattr(m, "_get_attach_list", lambda page, *a, **k: list(attach_list))
    monkeypatch.setattr(m, "download_feishu_file", lambda token, path: (open(path, "wb").write(b"%PDF-fake") or True))
    monkeypatch.setattr(m.time, "sleep", lambda *a, **k: None)

    def spy_upload(page, path, name):
        calls["upload"] += 1
        return True

    def spy_delete_all(page):
        calls["delete_all"] += 1
        return 0

    monkeypatch.setattr(m, "_upload_resume_to_51job", spy_upload)
    monkeypatch.setattr(m, "_delete_all_attachments", spy_delete_all)


_JOB = {"job_url": "https://www.51job.com/job/123.html", "mass_apply": True, "record_id": "", "file_token": "tok_test"}
_EXISTING = [{"id": "999", "name": m.MASS_RESUME_NAME, "status": "01"}]


def test_mass_session_reuse_no_repeat_upload(monkeypatch):
    calls = {"upload": 0, "delete_all": 0}
    _install_stubs(monkeypatch, calls, _EXISTING)

    # 场景1：「我的简历」今日已由本引擎上传（第 2+ 个岗位 / 后续波次 / 重启后的进程）→ 必须复用，不清空不上传
    monkeypatch.setattr(m, "_MASS_FORCE_UPLOAD", False)
    upload_quota.mark_mass_resume_uploaded_today()
    ok = m.deliver_job(dict(_JOB))
    print(f"\n[场景1] 当日复用分支: deliver={ok} 上传次数={calls['upload']} 清空次数={calls['delete_all']}")
    assert calls["upload"] == 0 and calls["delete_all"] == 0, "当日复用分支不应清空/上传！"

    # 场景2：新批量任务 reset 后首岗位，即便列表已有今日同名海投简历 → 强制重传当批最新版
    m.reset_mass_apply_session()
    calls["upload"] = 0; calls["delete_all"] = 0
    ok = m.deliver_job(dict(_JOB))
    print(f"\n[场景2] reset 后首岗位强制重传: deliver={ok} 上传次数={calls['upload']} 强制标志={m._MASS_FORCE_UPLOAD}")
    assert calls["upload"] == 1, "reset 后首岗位应强制重传当批最新海投简历！"
    assert m._MASS_FORCE_UPLOAD is False, "重传成功后应清除强制标志，后续岗位转入复用"

    # 场景3：列表为空 → 触发今日首次上传（恰好一次）
    monkeypatch.setattr(m, "_get_attach_list", lambda page, *a, **k: [])
    monkeypatch.setattr(upload_quota, "QUOTA_STATE_FILE", upload_quota.QUOTA_STATE_FILE + ".s3")
    calls["upload"] = 0; calls["delete_all"] = 0
    ok = m.deliver_job(dict(_JOB))
    print(f"\n[场景3] 空列表首发: deliver={ok} 上传次数={calls['upload']}")
    assert calls["upload"] == 1, "空列表应恰好上传一次！"
    assert upload_quota.is_mass_resume_fresh_today(), "海投上传成功后应回写当日新鲜度"
