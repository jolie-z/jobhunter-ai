import pytest
import tempfile
import sqlite3
from unittest.mock import patch, MagicMock
from app.automation import run_snapshot as rs


def test_run_snapshot_persistence(tmp_path):
    test_db = tmp_path / "test_raw_jobs.db"
    
    with patch.object(rs, "_DB_PATH", test_db):
        # 1. 开启一轮
        rs.begin("task_2026_0826", 100, {"boss": 10}, [])
        rs.register_record_ids(["rec_001", "rec_002"])
        rs.end()
        
        # 2. 模拟进程重启，重新加载
        rs._runtime["started"] = False
        rs._runtime["task_id"] = None
        rs._runtime["record_ids"] = []
        
        # 3. 验证调用 current_runtime 时能从 SQLite 自动恢复最新一轮台账
        rt = rs.current_runtime()
        assert rt["started"] is True
        assert rt["task_id"] == "task_2026_0826"
        assert rt["start_rowid"] == 100
        assert "rec_001" in rt["record_ids"]
        assert "rec_002" in rt["record_ids"]


def test_feishu_custom_vs_mass_classification():
    from app.services import feishu_service as fs
    
    mock_items = [
        {
            "record_id": "rec_custom_1",
            "fields": {
                "岗位名称": "AI产品经理",
                "公司名称": "高潜科技",
                "综合等级": "B",
                "跟进状态": "简历人工复核",
                "公司规模": "100-499人",
            }
        },
        {
            "record_id": "rec_mass_1",
            "fields": {
                "岗位名称": "产品运营",
                "公司名称": "大型集团",
                "综合等级": "C",
                "跟进状态": "简历人工复核",
                "公司规模": "10000人以上",
            }
        },
        {
            "record_id": "rec_eval_done_1",
            "fields": {
                "岗位名称": "初级助理",
                "公司名称": "中小公司",
                "综合等级": "C",
                "跟进状态": "已完成初步评估",
                "公司规模": "20-99人",
            }
        }
    ]
    
    with patch("app.services.feishu_service.get_tenant_access_token", return_value="mock_token"), \
         patch("app.services.feishu_service.safe_feishu_request") as mock_req:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 0,
            "data": {
                "items": mock_items,
                "has_more": False,
            }
        }
        mock_req.return_value = mock_resp
        
        jobs = fs.get_pending_review_jobs_from_feishu()
        assert len(jobs) == 3
        
        # 验证精投
        assert jobs[0]["job_id"] == "rec_custom_1"
        assert jobs[0]["is_custom"] is True
        assert jobs[0]["company_scale"] == "100-499人"
        
        # 验证海投人工复核
        assert jobs[1]["job_id"] == "rec_mass_1"
        assert jobs[1]["is_custom"] is False
        assert jobs[1]["company_scale"] == "10000人以上"
        
        # 验证已完成初步评估海投
        assert jobs[2]["job_id"] == "rec_eval_done_1"
        assert jobs[2]["is_custom"] is False
        assert jobs[2]["company_scale"] == "20-99人"


def test_full_auto_build_job_states_company_scale():
    from app.automation.full_auto import _build_job_states
    leads = [
        {
            "record_id": "rec_001",
            "platform": "boss",
            "company": "字节跳动",
            "job_title": "产品专家",
            "company_scale": "10000人以上",
            "salary": "30-50K",
            "city": "北京",
            "experience": "5-10年",
            "education": "本科",
            "jd_text": "负责核心业务",
        },
        {
            "record_id": "rec_002",
            "platform": "zhilian",
            "company": "初创科技",
            "job_title": "AI产品经理",
            "_raw_fields": {"公司规模": "20-99人"},
            "salary": "15-25K",
            "city": "广州",
        }
    ]
    states = _build_job_states(leads)
    assert len(states) == 2
    assert states[0]["company_scale"] == "10000人以上"
    assert states[1]["company_scale"] == "20-99人"

