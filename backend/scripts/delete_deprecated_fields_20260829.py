#!/usr/bin/env python3
"""备份并删除岗位表/简历库表的废弃字段（Word附件 ×2、人工精修版简历）。

用法（均在 backend 目录下）：
    .venv/bin/python -u scripts/delete_deprecated_fields_20260829.py probe    # 只读：定位 field_id + 非空计数
    .venv/bin/python -u scripts/delete_deprecated_fields_20260829.py backup   # 拉取非空数据落盘 backups/
    .venv/bin/python -u scripts/delete_deprecated_fields_20260829.py delete   # 校验备份存在后删除字段并复查

记录读取复用 app 自己的 feishu_client（httpx + 重试 + 分页防御），
规避 records/search 的 page_size/page_token 必须放 query 参数的坑。
"""
import asyncio
import json
import sys
import time
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
import os
os.chdir(backend_dir)

import httpx

from app.core.config import settings
from app.core.feishu_client import feishu_client

BACKUP_PATH = backend_dir / "backups" / "feishu_deleted_fields_backup_20260829.json"

TARGETS = {
    "岗位表": (settings.FEISHU_TABLE_ID_JOBS, ["Word附件", "人工精修版简历"]),
    "简历库表": (settings.FEISHU_TABLE_ID_RESUMES, ["Word附件"]),
}


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def list_fields_with_id(table_id: str) -> list[dict]:
    """列字段（拿 field_id，feishu_client.list_bitable_fields 只返回名字）"""
    token = await feishu_client.get_tenant_access_token()
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{feishu_client.app_token}/tables/{table_id}/fields"
    items, page_token = [], None
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        while True:
            params = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            data = await feishu_client._execute_request_with_retry(
                client, "GET", url, "列字段", params=params, headers=_headers(token))
            if data.get("code") != 0:
                raise SystemExit(f"列字段失败: {data}")
            items.extend(data["data"]["items"])
            page_token = data["data"].get("page_token")
            if not data["data"].get("has_more"):
                break
    return items


def _is_empty(v) -> bool:
    return v is None or v == "" or v == []


async def locate_targets() -> dict:
    """{label: {"table_id":…, "fields": {field_name: {"field_id":…, "type":…}}}}"""
    result = {}
    for label, (table_id, names) in TARGETS.items():
        fields = {f["field_name"]: f for f in await list_fields_with_id(table_id)}
        found = {}
        for name in names:
            f = fields.get(name)
            if not f:
                print(f"  ❌ [{label}] 未找到「{name}」")
            else:
                print(f"  ✅ [{label}]「{name}」field_id={f['field_id']} type={f['type']}")
                found[name] = f
        result[label] = {"table_id": table_id, "fields": found}
    return result


async def count_nonempty(table_id: str, names: list[str]) -> tuple[int, dict]:
    records = await feishu_client.search_bitable_records(table_id, field_names=names)
    counts = {n: 0 for n in names}
    for rec in records:
        for n in names:
            if not _is_empty(rec.get("fields", {}).get(n)):
                counts[n] += 1
    return len(records), counts


async def cmd_probe():
    located = await locate_targets()
    print()
    for label, info in located.items():
        if not info["fields"]:
            continue
        total, counts = await count_nonempty(info["table_id"], list(info["fields"]))
        print(f"[{label}] 记录总数 {total}，非空计数: {counts}")


async def cmd_backup():
    located = await locate_targets()
    backup = {"_meta": {
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "app_token": feishu_client.app_token,
        "purpose": "删除字段前备份：Word附件(岗位表/简历库表)、人工精修版简历(岗位表) 的非空数据",
        "fields": {label: list(info["fields"]) for label, info in located.items()},
        "table_ids": {label: info["table_id"] for label, info in located.items()},
    }, "tables": {}}

    for label, info in located.items():
        names = list(info["fields"])
        if not names:
            continue
        table_id = info["table_id"]
        records = await feishu_client.search_bitable_records(table_id, field_names=names)
        nonempty = {}
        for rec in records:
            payload = {n: rec["fields"][n] for n in names if not _is_empty(rec.get("fields", {}).get(n))}
            if payload:
                nonempty[rec["record_id"]] = payload
        backup["tables"][label] = nonempty
        counts = {n: sum(1 for p in nonempty.values() if n in p) for n in names}
        print(f"[{label}] 记录总数 {len(records)}，非空记录 {len(nonempty)} 条，分字段非空: {counts}")

    BACKUP_PATH.parent.mkdir(exist_ok=True)
    BACKUP_PATH.write_text(json.dumps(backup, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n💾 备份已写入: {BACKUP_PATH} ({BACKUP_PATH.stat().st_size} bytes)")


async def cmd_delete():
    if not BACKUP_PATH.exists():
        raise SystemExit(f"❌ 备份文件不存在，拒绝删除: {BACKUP_PATH}")
    backup = json.loads(BACKUP_PATH.read_text(encoding="utf-8"))
    for label, names in backup["_meta"]["fields"].items():
        table_data = backup["tables"].get(label, {})
        counts = {n: sum(1 for p in table_data.values() if n in p) for n in names}
        print(f"  备份校验 [{label}]: 字段 {names}，非空记录分字段 {counts}")

    token = await feishu_client.get_tenant_access_token()
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        for label, info in (await locate_targets()).items():
            table_id = info["table_id"]
            for name, f in info["fields"].items():
                url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{feishu_client.app_token}/tables/{table_id}/fields/{f['field_id']}"
                data = await feishu_client._execute_request_with_retry(
                    client, "DELETE", url, f"删除字段「{name}」", headers=_headers(token))
                if data.get("code") != 0:
                    raise SystemExit(f"❌ [{label}] 删除「{name}」失败: {data}")
                print(f"  🗑  [{label}] 已删除「{name}」(field_id={f['field_id']})")

    print("\n=== 删除后复查 ===")
    await cmd_probe()


async def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "probe":
        await cmd_probe()
    elif cmd == "backup":
        await cmd_backup()
    elif cmd == "delete":
        await cmd_delete()
    else:
        raise SystemExit("用法: probe | backup | delete")


if __name__ == "__main__":
    asyncio.run(main())
