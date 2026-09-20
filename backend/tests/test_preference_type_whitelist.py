"""Q-M4-3 回归：偏好 type 白名单——服务端拒绝任意字符串 type 直接入库。

仅测守卫分支（非法 type 在触碰数据库前即拒绝），不写生产库。
"""
import pytest

from app.strategy.config_service import (
    PREFERENCE_TYPE_WHITELIST,
    upsert_preference_service,
)
from app.strategy.schemas import PreferenceUpsertRequest


def test_whitelist_contains_frontend_three_types():
    assert PREFERENCE_TYPE_WHITELIST == {"核心加分", "职业愿景", "自动化阈值"}


@pytest.mark.asyncio
async def test_invalid_type_rejected_before_db():
    payload = PreferenceUpsertRequest(type="不存在的类型XYZ", rule="x", status="启用")
    with pytest.raises(ValueError, match="不支持的偏好类型"):
        await upsert_preference_service(payload)


@pytest.mark.parametrize("legal_type", ["核心加分", "职业愿景", "自动化阈值"])
async def test_legal_types_pass_guard(legal_type):
    """合法类型应通过守卫（不实际落库——mock 掉 DB 写入，仅验证守卫放行）"""
    from unittest.mock import MagicMock, patch

    payload = PreferenceUpsertRequest(type=legal_type, rule="QA守卫验证", status="停用")
    with patch("app.strategy.config_service.get_db_path", return_value="/tmp/qa_guard_should_not_touch.db"), \
         patch("sqlite3.connect", return_value=MagicMock()):
        # 守卫放行后进入 DB 分支（已被 mock），不抛 ValueError 即为通过
        await upsert_preference_service(payload)
