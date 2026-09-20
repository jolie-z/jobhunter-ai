import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from app.automation.routes.delivery_router import _deliver_approved_worker

@pytest.mark.asyncio
async def test_batch_orchestrator_sorting_and_mass_reuse():
    """验证批量投递编排器：
    1. 平台严格按 BOSS -> 智联 -> 猎聘 -> 51job 排序
    2. 单平台内严格按 精投优先 -> 海投垫后 排序
    3. 海投批次标志 batch_mass_uploaded 正确在岗位间递增复用
    """
    # 模拟 6 个混合平台和混合精海的岗位
    mock_records = {
        "job_zhilian_mass_1": {
            "fields": {"招聘平台": "智联招聘", "综合评级 (A-F)": "D", "公司名称": "智联海投A", "岗位名称": "产品经理"}
        },
        "job_boss_mass": {
            "fields": {"招聘平台": "BOSS直聘", "综合评级 (A-F)": "C", "公司名称": "BOSS海投A", "岗位名称": "项目经理"}
        },
        "job_51job_custom": {
            "fields": {"招聘平台": "51job", "综合评级 (A-F)": "B", "公司名称": "51精投A", "岗位名称": "开发工程师", "AI改写JSON": "{\"v\":2}"}
        },
        "job_zhilian_custom": {
            "fields": {"招聘平台": "智联招聘", "综合评级 (A-F)": "A", "公司名称": "智联精投A", "岗位名称": "AI产品经理", "AI改写JSON": "{\"v\":2}"}
        },
        "job_zhilian_mass_2": {
            "fields": {"招聘平台": "智联招聘", "综合评级 (A-F)": "D", "公司名称": "智联海投B", "岗位名称": "运营经理"}
        },
        "job_boss_custom": {
            "fields": {"招聘平台": "BOSS直聘", "综合评级 (A-F)": "A", "公司名称": "BOSS精投A", "岗位名称": "架构师", "AI改写JSON": "{\"v\":2}"}
        },
    }

    input_thread_ids = [
        "job_zhilian_mass_1",
        "job_boss_mass",
        "job_51job_custom",
        "job_zhilian_custom",
        "job_zhilian_mass_2",
        "job_boss_custom",
    ]

    executed_order = []
    mass_uploaded_states = []

    async def mock_deliver_helper(t_id: str, item: dict, batch_mass_uploaded: bool = False):
        executed_order.append(t_id)
        mass_uploaded_states.append((t_id, batch_mass_uploaded))
        return True

    with patch("app.services.feishu_service.get_job_record_from_feishu", side_effect=lambda t_id, tbl: mock_records.get(t_id)), \
         patch("app.automation.routes.delivery_router._deliver_single_job_helper", side_effect=mock_deliver_helper):
        
        await _deliver_approved_worker(input_thread_ids)

    # 1. 验证执行顺序：
    # BOSS(精投) -> BOSS(海投) -> 智联(精投) -> 智联(海投1) -> 智联(海投2) -> 51job(精投)
    expected_order = [
        "job_boss_custom",
        "job_boss_mass",
        "job_zhilian_custom",
        "job_zhilian_mass_1",
        "job_zhilian_mass_2",
        "job_51job_custom",
    ]
    assert executed_order == expected_order, f"实际执行顺序不符合预期: {executed_order}"

    # 2. 验证海投复用状态：
    # 智联精投: batch_mass_uploaded = False
    # 智联海投1: batch_mass_uploaded = False (首发需删旧上传)
    # 智联海投2: batch_mass_uploaded = True  (次发直接复用)
    state_dict = dict(mass_uploaded_states)
    assert state_dict["job_zhilian_custom"] is False
    assert state_dict["job_zhilian_mass_1"] is False
    assert state_dict["job_zhilian_mass_2"] is True
    assert state_dict["job_51job_custom"] is False
