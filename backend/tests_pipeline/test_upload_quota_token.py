"""2026-10-08 51job 海投新鲜度内容维度回归：母本当天重新生成（file_token 变化）后，
当日已传的旧附件不再被判新鲜复用（防投出旧版简历）。

跑法：cd backend && .venv/bin/python -m pytest tests_pipeline/test_upload_quota_token.py -q
"""
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.automation import upload_quota


def _isolated_state_file(tmp_path, monkeypatch):
    state_file = tmp_path / "51job_upload_quota.json"
    monkeypatch.setattr(upload_quota, "QUOTA_STATE_FILE", str(state_file))
    return state_file


def test_token_mismatch_means_not_current(tmp_path, monkeypatch):
    _isolated_state_file(tmp_path, monkeypatch)
    upload_quota.mark_mass_resume_uploaded_today("boxOld")
    assert upload_quota.is_mass_resume_fresh_today()
    # 母本当天重新生成 → 飞书给了新 token → 内容不再"最新"
    assert not upload_quota.is_mass_resume_content_current("boxNew")
    assert upload_quota.is_mass_resume_content_current("boxOld")


def test_empty_token_keeps_legacy_reuse(tmp_path, monkeypatch):
    _isolated_state_file(tmp_path, monkeypatch)
    upload_quota.mark_mass_resume_uploaded_today("")  # 旧调用兼容：无 token 记录
    # 无 token 记录 = 无法判定内容是否变化 → 维持既有"当日复用"行为（不白烧配额），
    # 本次真实上传后 mark_mass_resume_uploaded_today(file_token) 会补记 token
    assert upload_quota.is_mass_resume_content_current("anything")
    assert upload_quota.is_mass_resume_content_current("")


def test_cross_day_resets_token(tmp_path, monkeypatch):
    _isolated_state_file(tmp_path, monkeypatch)
    upload_quota.mark_mass_resume_uploaded_today("boxOld")
    # 模拟跨天：状态文件日期被改写为昨天
    with open(upload_quota.QUOTA_STATE_FILE, encoding="utf-8") as f:
        data = json.load(f)
    data["date"] = "2000-01-01"
    with open(upload_quota.QUOTA_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)
    assert not upload_quota.is_mass_resume_fresh_today()  # 跨天状态归零
    # 跨天后 token 记录随之清空 → 按三值语义返回 True（无记录=维持既有复用）；
    # 但 fresh_today 已为 False，引擎不会进入当日复用分支，token 值无实际影响
    assert upload_quota.is_mass_resume_content_current("boxOld")
