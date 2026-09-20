"""智联 SnapshotManager 真实生命周期回归（承接自被删的游离测试，2026-09-20）。

覆盖：create_snapshot 落盘、list_snapshots 可见、rollback 恢复内容、
超上限自动清理。全部走 tmp_path，零生产接触。
"""
import json
import os
from unittest import mock

from resume_editor.platforms.zhilian_probe_healer import SnapshotManager


def test_snapshot_manager_lifecycle(tmp_path):
    """快照创建、列表查询、超出上限自动清理与回滚恢复"""
    test_snapshots_dir = tmp_path / "snapshots"
    test_writeback_file = tmp_path / "zhilian_writeback.json"

    initial_content = json.dumps({"test": "version_1"}, ensure_ascii=False)
    test_writeback_file.write_text(initial_content, encoding="utf-8")

    with mock.patch("resume_editor.platforms.zhilian_probe_healer.SNAPSHOTS_DIR", str(test_snapshots_dir)), \
         mock.patch("resume_editor.platforms.zhilian_probe_healer.WRITEBACK_FILE", str(test_writeback_file)):
        mgr = SnapshotManager(max_snapshots=3)

        # 1. 创建快照并落盘
        s1 = mgr.create_snapshot(prefix="test_snap")
        assert s1 is not None
        assert os.path.exists(os.path.join(str(test_snapshots_dir), s1))

        # 2. 列表可见（list_snapshots 的 prefix 过滤须与 create 一致）
        snaps = mgr.list_snapshots(prefix="test_snap")
        assert any(s.get("id") == s1 or s1 in str(s) for s in snaps)

        # 3. 修改后回滚恢复 version_1
        test_writeback_file.write_text(json.dumps({"test": "version_2"}, ensure_ascii=False), encoding="utf-8")
        ok, msg = mgr.rollback(snapshot_id=s1, prefix="test_snap")
        assert ok, msg
        assert json.loads(test_writeback_file.read_text(encoding="utf-8")) == {"test": "version_1"}

        # 4. 超上限自动清理最旧
        for i in range(4):
            test_writeback_file.write_text(json.dumps({"test": f"v_{i}"}, ensure_ascii=False), encoding="utf-8")
            mgr.create_snapshot(prefix="test_snap")
        assert len(mgr.list_snapshots(prefix="test_snap")) <= 3
