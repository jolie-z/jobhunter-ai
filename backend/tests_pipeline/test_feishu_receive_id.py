"""飞书接收ID格式校验测试：网页URL等非法值必须被判非法，避免再出现 400 静默失败。"""
from app.core.feishu_messaging import is_valid_receive_id


def test_receive_id_validation():
    assert is_valid_receive_id("oc_a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6") is True
    assert is_valid_receive_id("ou_da5xxxxxxxxxxxxdfe") is True
    # 网页地址（历史事故值）必须非法
    assert is_valid_receive_id("http://localhost:3000/prototype/command-center") is False
    assert is_valid_receive_id("") is False
    assert is_valid_receive_id(None) is False
