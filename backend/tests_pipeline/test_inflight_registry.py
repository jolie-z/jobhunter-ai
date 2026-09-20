"""进行中评估登记表（inflight_registry）单测。

覆盖：登记/查询/注销/物料已交付标记的完整生命周期、
跨实例落盘持久化、过期 TTL 兜底清理。
"""
import time

import pytest

from app.automation import inflight_registry as reg


@pytest.fixture(autouse=True)
def _tmp_registry(tmp_path):
    reg.reset_for_test(tmp_path / "inflight_pipelines.json")
    yield
    reg.reset_for_test()


def test_register_and_get_roundtrip():
    reg.register("rec1", chat_id="oc_a", card_msg_id="om_card1", company="唯品会", job="AI产品运营")
    assert reg.has("rec1")
    entry = reg.get("rec1")
    assert entry["chat_id"] == "oc_a"
    assert entry["card_msg_id"] == "om_card1"
    assert entry["company"] == "唯品会"
    assert entry["job"] == "AI产品运营"
    assert entry["materials_delivered"] is False
    assert 0 < time.time() - entry["started_epoch"] < 5
    assert list(reg.list_entries().keys()) == ["rec1"]


def test_unregister_removes_entry():
    reg.register("rec1", chat_id="oc_a", card_msg_id="om1")
    assert reg.has("rec1")
    reg.unregister("rec1")
    assert not reg.has("rec1")
    assert reg.get("rec1") is None


def test_unregister_missing_is_noop():
    reg.unregister("rec_missing")  # 不应抛异常
    assert not reg.has("rec_missing")


def test_mark_materials_delivered():
    reg.register("rec1", chat_id="oc_a", card_msg_id="om1")
    reg.mark_materials_delivered("rec1")
    assert reg.get("rec1")["materials_delivered"] is True
    # 未登记的 record 不应报错
    reg.mark_materials_delivered("rec_missing")


def test_persistence_across_cache_reset():
    started = time.time() - 60
    reg.register("rec1", chat_id="oc_a", card_msg_id="om1", started_epoch=started)
    reg.reset_for_test()  # 只清内存缓存，文件还在 → 模拟进程重启后重新加载
    entry = reg.get("rec1")
    assert entry is not None
    assert entry["chat_id"] == "oc_a"
    assert entry["started_epoch"] == started


def test_ttl_prune_on_load():
    reg.register("rec_old", chat_id="oc_a", card_msg_id="om1",
                 started_epoch=time.time() - 25 * 3600)
    reg.register("rec_new", chat_id="oc_a", card_msg_id="om2")
    reg.reset_for_test()  # 触发重新加载
    assert not reg.has("rec_old"), "超过 24h 的登记项应被兜底清理"
    assert reg.has("rec_new")


def test_register_overwrites_same_record():
    reg.register("rec1", chat_id="oc_a", card_msg_id="om1")
    reg.register("rec1", chat_id="oc_b", card_msg_id="om2")
    entry = reg.get("rec1")
    assert entry["chat_id"] == "oc_b"
    assert len(reg.list_entries()) == 1
