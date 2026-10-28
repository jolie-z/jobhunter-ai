"""get_auto_eval_threshold 读库路径修复回归（2026-10-08 批量初评 B 级不流转深评事故）。

根因：ai_evaluator 硬编码 backend/data 相对路径，打包形态（JOBHUNTER_DATA_DIR 注入）
该文件不存在 → 永远命中「不存在 → A」兜底，用户设置的阈值从未被读到。
修复后必须从 job_hunter_db_path 真源（JOBHUNTER_DATA_DIR）读取。
"""

import sqlite3
import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_BACKEND_ROOT),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ai_agents.ai_evaluator import get_auto_eval_threshold


def _seed_threshold_db(db_path: Path, rule: str):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS job_preferences (type TEXT, rule TEXT, status TEXT)")
        conn.execute(
            "INSERT INTO job_preferences (type, rule, status) VALUES ('自动化阈值', ?, '启用')",
            (rule,),
        )
        conn.commit()
    finally:
        conn.close()


def test_threshold_reads_from_jobhunter_data_dir(monkeypatch, tmp_path):
    """打包形态主场景：JOBHUNTER_DATA_DIR 指向用户数据目录，阈值 B 必须被读到。

    修复前：硬编码 backend/data 锚点在该形态下不存在 → 恒返回 A（设置显示 B、运行按 A）。
    """
    monkeypatch.setenv("JOBHUNTER_DATA_DIR", str(tmp_path))
    _seed_threshold_db(tmp_path / "job_hunter.db", "B")
    assert get_auto_eval_threshold() == "B"


def test_threshold_respects_single_file_env_override(monkeypatch, tmp_path):
    """JOBHUNTER_DB_PATH 单文件覆盖优先级最高（db_paths 契约）。"""
    side_db = tmp_path / "side.db"
    _seed_threshold_db(side_db, "C")
    monkeypatch.setenv("JOBHUNTER_DATA_DIR", str(tmp_path / "unused"))
    monkeypatch.setenv("JOBHUNTER_DB_PATH", str(side_db))
    assert get_auto_eval_threshold() == "C"


def test_threshold_defaults_a_when_db_missing(monkeypatch, tmp_path):
    """库不存在（全新安装）→ A 兜底，且绝不静默创建空库文件。"""
    monkeypatch.setenv("JOBHUNTER_DATA_DIR", str(tmp_path))
    assert get_auto_eval_threshold() == "A"
    assert not (tmp_path / "job_hunter.db").exists()


def test_threshold_falls_back_a_when_table_missing(monkeypatch, tmp_path):
    """库存在但无 job_preferences 表（异常态）→ A 兜底不抛错。"""
    monkeypatch.setenv("JOBHUNTER_DATA_DIR", str(tmp_path))
    (tmp_path / "job_hunter.db").write_bytes(b"")
    assert get_auto_eval_threshold() == "A"
