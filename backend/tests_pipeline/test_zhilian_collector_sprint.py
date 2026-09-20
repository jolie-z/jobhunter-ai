import sys
import sqlite3
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
if str(backend_dir / "zhilian_scraper") not in sys.path:
    sys.path.insert(0, str(backend_dir / "zhilian_scraper"))

# zhilian_collector 与 resume_editor/platforms 下同名模块裸名冲突，显式按路径加载爬虫侧模块
import importlib.util

_collector_spec = importlib.util.spec_from_file_location(
    "zhilian_collector_scraper", backend_dir / "zhilian_scraper" / "zhilian_collector.py"
)
zc = importlib.util.module_from_spec(_collector_spec)
sys.modules[_collector_spec.name] = zc
_collector_spec.loader.exec_module(zc)


def test_memory_fingerprints_and_check_exists(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_raw_jobs.db")
    monkeypatch.setattr(zc, "DB_PATH", test_db)
    
    # Reset globals
    zc._KNOWN_JOB_LINKS = set()
    zc._KNOWN_JOB_ENTITIES = set()
    zc._FINGERPRINTS_LOADED = False
    
    with sqlite3.connect(test_db) as conn:
        conn.execute("""
            CREATE TABLE raw_jobs (
                job_link TEXT, company_name TEXT, job_title TEXT, city TEXT, platform TEXT
            )
        """)
        conn.execute(
            "INSERT INTO raw_jobs VALUES (?, ?, ?, ?, ?)",
            ("https://www.zhaopin.com/job/123.htm?ref=test", "测试企业A", "Python开发", "广州", "智联招聘")
        )
        conn.commit()
        
    # Check exists with memory preload
    assert zc.check_job_exists("测试企业A", "Python开发", "广州", "https://www.zhaopin.com/job/123.htm") is True
    assert zc.check_job_exists("新企业B", "前端开发", "广州", "https://www.zhaopin.com/job/999.htm") is False
    
    # Test register new job
    zc._register_job_to_memory({
        "job_link": "https://www.zhaopin.com/job/999.htm?ref=abc",
        "company_name": "新企业B",
        "job_title": "前端开发",
        "city": "广州"
    })
    assert zc.check_job_exists("新企业B", "前端开发", "广州", "https://www.zhaopin.com/job/999.htm") is True


def test_process_job_batch_sprint_mode(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_raw_jobs.db")
    monkeypatch.setattr(zc, "DB_PATH", test_db)
    
    zc._KNOWN_JOB_LINKS = {"https://www.zhaopin.com/job/1.htm", "https://www.zhaopin.com/job/2.htm"}
    zc._KNOWN_JOB_ENTITIES = {("公司A", "岗位A", "广州"), ("公司B", "岗位B", "广州")}
    zc._FINGERPRINTS_LOADED = True
    
    card1 = MagicMock()
    card2 = MagicMock()
    
    def mock_extract(ele, city):
        if ele == card1:
            return {"job_link": "https://www.zhaopin.com/job/1.htm", "company_name": "公司A", "job_title": "岗位A", "city": city}
        return {"job_link": "https://www.zhaopin.com/job/2.htm", "company_name": "公司B", "job_title": "岗位B", "city": city}
        
    monkeypatch.setattr(zc, "_extract_job_basic_info", mock_extract)
    
    page = MagicMock()
    success, skip, is_sprint = zc._process_job_batch(page, [card1, card2], "广州", target=10, success_count=0, skip_count=0, current_page=1)
    
    assert is_sprint is True
    assert skip == 2
    assert success == 0


def test_process_job_batch_fresh_mode(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_raw_jobs.db")
    monkeypatch.setattr(zc, "DB_PATH", test_db)
    
    zc._KNOWN_JOB_LINKS = {"https://www.zhaopin.com/job/1.htm"}
    zc._KNOWN_JOB_ENTITIES = {("公司A", "岗位A", "广州")}
    zc._FINGERPRINTS_LOADED = True
    
    card1 = MagicMock()
    card2 = MagicMock()
    
    def mock_extract(ele, city):
        if ele == card1:
            return {"job_link": "https://www.zhaopin.com/job/1.htm", "company_name": "公司A", "job_title": "岗位A", "city": city}
        return {"job_link": "https://www.zhaopin.com/job/fresh.htm", "company_name": "新鲜公司", "job_title": "新鲜岗位", "city": city}
        
    monkeypatch.setattr(zc, "_extract_job_basic_info", mock_extract)
    
    def mock_fresh_card(page, ele, data, city, idx, total):
        return data, False
        
    monkeypatch.setattr(zc, "_process_single_fresh_card", mock_fresh_card)
    
    page = MagicMock()
    success, skip, is_sprint = zc._process_job_batch(page, [card1, card2], "广州", target=10, success_count=0, skip_count=0, current_page=1)
    
    assert is_sprint is False
    assert skip == 1
    assert success == 1
