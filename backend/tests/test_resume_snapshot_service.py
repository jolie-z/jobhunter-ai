"""resume_snapshot_service 落盘/读回/修正回流测试（SNAPSHOT_ROOT 重定向到 tmp_path）。"""

import json

import pytest

from app.services import resume_snapshot_service as svc


@pytest.fixture()
def snapshot_root(tmp_path, monkeypatch):
    root = tmp_path / "snapshots"
    monkeypatch.setattr(svc, "SNAPSHOT_ROOT", root)
    return root


SAMPLE = {
    "summary": "五年电商与 AI 应用全栈经验，主导过多个业务级 SaaS 产品",
    "workExperience": [{"company": "A", "description": "负责核心微服务架构设计与落地"}],
    "personalInfo": {"name": "测试"},
}


def test_save_snapshot_writes_bundle_and_meta(snapshot_root):
    out = svc.save_snapshot("task-abc_1", b"%PDF-1.4 fake", "简历.pdf", "原始全文", SAMPLE)
    sdir = snapshot_root / "task-abc_1"
    assert (sdir / "source.pdf").read_bytes() == b"%PDF-1.4 fake"
    assert (sdir / "original.md").read_text(encoding="utf-8") == "原始全文"
    parsed = json.loads((sdir / "parsed.json").read_text(encoding="utf-8"))
    assert parsed["summary"] == SAMPLE["summary"]
    assert "_meta" not in parsed
    meta = json.loads((sdir / "meta.json").read_text(encoding="utf-8"))
    assert meta["snapshot_id"] == "task-abc_1"
    assert meta["source_filename"] == "简历.pdf"
    assert meta["confidence"]["summary"] == "high"
    # 返回值挂 _meta 且 personalInfo 保留
    assert out["_meta"]["snapshot_id"] == "task-abc_1"
    assert out["personalInfo"] == {"name": "测试"}


def test_get_snapshot_roundtrip(snapshot_root):
    svc.save_snapshot("task-x", b"bytes", "r.docx", "md text", SAMPLE)
    snap = svc.get_snapshot("task-x")
    assert snap is not None
    assert snap["original_markdown"] == "md text"
    assert snap["source_available"] is True
    assert snap["source_filename"] == "r.docx"
    assert svc.get_snapshot("nonexistent") is None


def test_get_snapshot_file_rejects_traversal(snapshot_root):
    with pytest.raises(ValueError):
        svc.snapshot_dir("../evil")
    with pytest.raises(ValueError):
        svc.snapshot_dir("a/b")
    assert svc.get_snapshot_file("nonexistent") is None


def test_retry_overwrites_parsed_but_keeps_snapshot_id(snapshot_root):
    svc.save_snapshot("task-r", b"b", "f.pdf", "md", SAMPLE)
    revised = dict(SAMPLE, summary="重试后结构化的全新总结内容，明显不同")
    out = svc.update_snapshot_parsed("task-r", revised)
    assert out["_meta"]["snapshot_id"] == "task-r"
    parsed = json.loads((snapshot_root / "task-r" / "parsed.json").read_text(encoding="utf-8"))
    assert "重试后" in parsed["summary"]


def test_record_corrections_diff_and_dedup(snapshot_root, tmp_path, monkeypatch):
    svc.save_snapshot("task-c", b"b", "f.pdf", "md", SAMPLE)
    calls = []

    # DB 指向临时文件，避免污染主库
    monkeypatch.setattr(svc, "resolve_main_db_path", lambda: str(tmp_path / "t.db"))

    # 未修改 → 0 条
    assert svc.record_corrections("task-c", dict(SAMPLE)) == 0
    # 修改 summary → 1 条
    changed = dict(SAMPLE, summary="用户手工重写的总结，与初始解析完全不同")
    assert svc.record_corrections("task-c", changed) == 1
    calls.append("first")
    # 同内容再保存 → 去重 0 条
    assert svc.record_corrections("task-c", changed) == 0
    # 再改成另一版本 → 又 1 条
    changed2 = dict(SAMPLE, summary="用户第二次改写，内容又不一样了用于验证多条记录")
    assert svc.record_corrections("task-c", changed2) == 1

    rows = svc.list_corrections(limit=10)
    assert len(rows) == 2
    assert rows[0]["module_key"] == "summary"
    assert "第二次改写" in rows[0]["corrected_text"]


def test_record_corrections_ignores_meta_changes(snapshot_root, tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "resolve_main_db_path", lambda: str(tmp_path / "t.db"))
    svc.save_snapshot("task-m", b"b", "f.pdf", "md", SAMPLE)
    # 只动 _meta/personalInfo → 不算内容修正
    noisy = dict(SAMPLE, _meta={"snapshot_id": "task-m", "confidence": {"summary": "confirmed"}})
    assert svc.record_corrections("task-m", noisy) == 0
