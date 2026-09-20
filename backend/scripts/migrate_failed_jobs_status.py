import os
import sys
import json
import argparse
from pathlib import Path

# 将 backend 加入 sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.services.feishu_service import (
    feishu_field_to_plain_str,
    update_feishu_record,
    get_job_record_from_feishu,
)
from app.automation.run_snapshot import get_delivery_failures

BACKUP_PATH = backend_dir / "data" / "backup_failed_jobs_before_fix.json"


def run_migration(dry_run: bool = False, force: bool = False):
    print(f"🚀 开始执行历史失败岗位状态归正迁移 (dry_run={dry_run})...")

    # 1. 获取本地失败台账
    local_failures = get_delivery_failures()
    print(f"📊 本地 SQLite 失败台账记录数: {len(local_failures)}")

    # 2. 收集需要归正的记录 ID 与信息
    # 优先保证本地失败台账的 33 个岗位全部写入飞书「投递失败」
    to_update_map = {}

    for jid, info in local_failures.items():
        rec = get_job_record_from_feishu(jid, settings.FEISHU_TABLE_ID_JOBS)
        original_fields = rec.get("fields", {}) if rec else {}
        curr_status = feishu_field_to_plain_str(original_fields.get("跟进状态", "")).strip()
        # 保护已投递成功的记录
        if curr_status == "已投递":
            print(f"⏭️ 岗位 {jid} 当前飞书门牌已为「已投递」，跳过归正")
            continue

        to_update_map[jid] = {
            "record_id": jid,
            "job_name": info.get("job_name") or feishu_field_to_plain_str(original_fields.get("岗位名称", "")),
            "comp_name": info.get("company") or feishu_field_to_plain_str(original_fields.get("公司名称", "")),
            "error": info.get("error") or "历史自动投递执行失败",
            "original_fields": original_fields
        }

    print(f"📥 确认需要归正为【投递失败】的本地台账岗位数: {len(to_update_map)}")

    if dry_run:
        print("🔍 [Dry Run 预览] 将被更新为「投递失败」的记录列表:")
        for item in to_update_map.values():
            print(f"   - [{item['record_id']}] {item['comp_name']} | {item['job_name']} | 原状态: '{item['original_fields'].get('跟进状态')}' | 原因: {item['error'][:60]}")
        print("✅ Dry Run 结束，未执行实际写操作与备份写入。")
        return

    # 3. 备份原始记录（若备份文件已存在且未指定 force，严禁覆盖历史初始备份）
    BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    if BACKUP_PATH.exists() and not force:
        print(f"ℹ️ 历史基线备份文件已存在: {BACKUP_PATH}，未指定 --force，跳过覆盖写以保护初次回滚基线")
    else:
        with open(BACKUP_PATH, "w", encoding="utf-8") as f:
            json.dump(list(to_update_map.values()), f, ensure_ascii=False, indent=2)
        print(f"💾 已备份 {len(to_update_map)} 条待修改记录到: {BACKUP_PATH}")

    # 4. 执行写入
    success_count = 0
    fail_count = 0

    for item in to_update_map.values():
        rec_id = item["record_id"]
        update_data = {
            "跟进状态": "投递失败",
            "自动投递失败日志": item["error"]
        }
        ok = update_feishu_record(rec_id, update_data)
        if ok:
            success_count += 1
            print(f"   ✅ [{rec_id}] 成功归正为「投递失败」: {item['comp_name']} | {item['job_name']}")
        else:
            fail_count += 1
            print(f"   ❌ [{rec_id}] 归正失败: {item['comp_name']} | {item['job_name']}")

    print(f"\n🏁 归正完成: 成功 {success_count} 个, 失败 {fail_count} 个")

    # 5. 读回验证闭环
    verified_count = 0
    for item in to_update_map.values():
        rec = get_job_record_from_feishu(item["record_id"], settings.FEISHU_TABLE_ID_JOBS)
        if rec:
            st = feishu_field_to_plain_str(rec.get("fields", {}).get("跟进状态", ""))
            if st == "投递失败":
                verified_count += 1
    print(f"🔍 读回校验结果: 飞书确认生效为「投递失败」的记录数: {verified_count} / {len(to_update_map)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="历史失败岗位状态归正脚本")
    parser.add_argument("--dry-run", action="store_true", help="仅预览分析结果，不执行实际写入")
    parser.add_argument("--force", action="store_true", help="强制覆盖已有的基线备份文件")
    args = parser.parse_args()
    run_migration(dry_run=args.dry_run, force=args.force)
