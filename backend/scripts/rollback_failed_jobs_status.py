import os
import sys
import json
import argparse
from pathlib import Path

# 将 backend 加入 sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.services.feishu_service import (
    update_feishu_record,
    feishu_field_to_plain_str
)

BACKUP_PATH = backend_dir / "data" / "backup_failed_jobs_before_fix.json"


def run_rollback(dry_run: bool = False):
    print(f"🔄 开始执行历史状态回滚 (dry_run={dry_run})...")

    if not BACKUP_PATH.exists():
        raise FileNotFoundError(f"备份文件不存在: {BACKUP_PATH}")

    with open(BACKUP_PATH, "r", encoding="utf-8") as f:
        backup_items = json.load(f)

    print(f"📖 读取到备份记录数: {len(backup_items)}")

    success_count = 0
    fail_count = 0

    for item in backup_items:
        rec_id = item.get("record_id")
        fields = item.get("original_fields", {})
        original_status = feishu_field_to_plain_str(fields.get("跟进状态", ""))
        original_fail_log = feishu_field_to_plain_str(fields.get("自动投递失败日志", ""))
        job_name = item.get("job_name", "")
        comp_name = item.get("comp_name", "")

        if dry_run:
            print(f"   [Dry Run] 将恢复记录 {rec_id} ({comp_name} | {job_name}) 为 跟进状态='{original_status}'")
            continue

        if not original_status:
            print(f"   ⚠️ [{rec_id}] 备份中原始「跟进状态」为空，跳过还原以防清空飞书字段: {comp_name} | {job_name}")
            continue

        update_data = {
            "跟进状态": original_status,
            "自动投递失败日志": original_fail_log
        }

        ok = update_feishu_record(rec_id, update_data)
        if ok:
            success_count += 1
            print(f"   ✅ [{rec_id}] 已还原状态: {comp_name} | {job_name}")
        else:
            fail_count += 1
            print(f"   ❌ [{rec_id}] 还原失败: {comp_name} | {job_name}")

    if not dry_run:
        print(f"\n🏁 回滚完成: 成功 {success_count} 个, 失败 {fail_count} 个")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="历史失败岗位状态回滚脚本")
    parser.add_argument("--dry-run", action="store_true", help="仅预览回滚动作，不执行实际写入")
    args = parser.parse_args()
    run_rollback(dry_run=args.dry_run)
