#!/usr/bin/env python3
"""一次性运维脚本（2026-09-20）：制作开源用的飞书多维表格模板副本。

对应方案：docs/plans/飞书开源模板方案.md §2（复制副本→清空个人数据→脱敏→发布）。

子命令（按顺序执行）：
  inspect        只读：列出生产 Base 的全部表与记录数
  copy           复制整本 Base 为模板副本（先试 bitable v2 副本接口，回落 drive v1）
  inspect-copy   只读：列出副本的表与记录数
  clean          清空指定表全部记录（--table tblXXX 可多值；--yes 才执行）
  delete-table   删除整张表（--table + --expect-name 双重校验；--yes 才执行）
  examples       往岗位表写入 3 条明显虚构的示例行（--yes 才执行）
  chat-members   列出 ChatOps 群成员（用于找用户 open_id）
  add-collaborator  把用户加为副本协作者（full_access；--yes 才执行）
  set-public     把副本链接设为「互联网上获得链接的任何人可阅读」（等脱敏确认后再跑）
  verify         只读：复核副本表结构与记录数

安全铁律：
- 所有破坏性操作的目标只能是副本 app_token；与生产 FEISHU_APP_TOKEN 相同直接拒绝。
- clean/delete-table/examples/add-collaborator 必须显式 --yes 才会写。
- 凭证只从 backend/.env 读取，脚本不打印任何 secret。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "https://open.feishu.cn/open-apis"
STATE_PATH = Path("/tmp/bitable_template_state.json")
SCRIPT_DIR = Path(__file__).resolve().parent
ENV_PATH = SCRIPT_DIR.parent / ".env"

# 模板里保留并需要清空个人数据的五张表（按名称识别，方案 §1.1）
TEMPLATE_TABLE_NAMES = [
    "岗位数据汇总表",
    "我的简历库",
    "个人专属面经库",
    "单篇面经情报库",
    "面经高频题库",
]
ARCHIVE_TABLE_KEYWORD = "已下架归档"


def die(msg: str) -> None:
    print(f"[FATAL] {msg}")
    sys.exit(1)


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


ENV = load_env()
PROD_APP_TOKEN = ENV.get("FEISHU_APP_TOKEN", "")
if not PROD_APP_TOKEN:
    die("backend/.env 缺少 FEISHU_APP_TOKEN")


def tenant_access_token() -> str:
    app_id = ENV.get("FEISHU_APP_ID", "")
    app_secret = ENV.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        die("backend/.env 缺少 FEISHU_APP_ID / FEISHU_APP_SECRET")
    body = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/auth/v3/tenant_access_token/internal",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    if payload.get("code") != 0:
        die(f"获取 tenant_access_token 失败：code={payload.get('code')} msg={payload.get('msg')}")
    return payload["tenant_access_token"]


_TOKEN: str | None = None


def get_token() -> str:
    global _TOKEN
    if _TOKEN is None:
        _TOKEN = tenant_access_token()
    return _TOKEN


def api(method: str, path: str, body: dict | None = None, params: dict | None = None) -> dict:
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {get_token()}")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        return {"code": exc.code, "msg": f"HTTP {exc.code}: {detail}"}
    except urllib.error.URLError as exc:
        return {"code": -1, "msg": f"网络错误 URLError: {exc}"}


# ---------- 通用：Base 元数据 ----------

def list_tables(app_token: str) -> list[dict]:
    tables: list[dict] = []
    page_token = ""
    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        payload = api("GET", f"/bitable/v1/apps/{app_token}/tables", params=params)
        if payload.get("code") != 0:
            die(f"list tables 失败：{payload.get('code')} {payload.get('msg')}")
        data = payload.get("data", {})
        tables.extend(data.get("items", []))
        if not data.get("has_more"):
            break
        page_token = data.get("page_token", "")
    return tables


def list_record_ids(app_token: str, table_id: str) -> list[str]:
    ids: list[str] = []
    page_token = ""
    while True:
        params: dict = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        payload = api(
            "GET",
            f"/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            params=params,
        )
        if payload.get("code") != 0:
            die(f"list records 失败（{table_id}）：{payload.get('code')} {payload.get('msg')}")
        data = payload.get("data", {})
        items = data.get("items") or []
        ids.extend(item["record_id"] for item in items)
        if not data.get("has_more"):
            break
        page_token = data.get("page_token", "")
    return ids


def print_tables(app_token: str, tag: str) -> list[dict]:
    tables = list_tables(app_token)
    print(f"\n[{tag}] 共 {len(tables)} 张表：")
    for t in tables:
        tid, name = t["table_id"], t.get("name", "")
        if name in TEMPLATE_TABLE_NAMES or ARCHIVE_TABLE_KEYWORD in name:
            count = len(list_record_ids(app_token, tid))
            print(f"  - {name}: {tid}（{count} 条记录）")
        else:
            print(f"  - {name}: {tid}（记录数未扫描）")
    return tables


# ---------- 安全护栏 ----------

def require_copy_app(args: argparse.Namespace) -> str:
    explicit = getattr(args, "app_token", "") or ""
    app = explicit or read_state().get("copy_app_token", "")
    if not app:
        die("没有副本 app_token，请先执行 copy")
    if app == PROD_APP_TOKEN:
        die("拒绝执行：目标 app_token 是生产 Base！破坏性操作只允许作用于副本。")
    state_copy = read_state().get("copy_app_token", "")
    if explicit and state_copy and explicit != state_copy:
        print(f"[WARN] 显式 --app-token 与状态文件里的副本不一致（{app} ≠ {state_copy}），请核对目标")
    return app


def require_yes(args: argparse.Namespace, action: str) -> None:
    if not getattr(args, "yes", False):
        die(f"{action} 是写操作，确认无误后加 --yes 执行")


def read_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def write_state(patch: dict) -> None:
    state = read_state()
    state.update(patch)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(STATE_PATH, 0o600)


# ---------- 子命令 ----------

def cmd_inspect(_args: argparse.Namespace) -> None:
    print_tables(PROD_APP_TOKEN, "生产 Base")


def cmd_copy(args: argparse.Namespace) -> None:
    if read_state().get("copy_app_token"):
        die(f"状态文件已有副本 {read_state()['copy_app_token']}，如需重做请先清理 {STATE_PATH}")
    name = args.name

    print(f"[1/2] 尝试 bitable v2 副本接口 …")
    payload = api("POST", f"/bitable/v2/apps/{PROD_APP_TOKEN}/copy", {"name": name})
    if payload.get("code") == 0:
        data = payload.get("data", {})
        new_token = data.get("app_token") or data.get("token") or ""
        print(json.dumps(payload.get("data", {}), ensure_ascii=False, indent=2))
        if new_token:
            write_state({"copy_app_token": new_token, "prod_app_token": PROD_APP_TOKEN, "copy_url": data.get("url", "")})
            print(f"[OK] v2 复制成功：{new_token}")
            return
        print("[WARN] v2 code=0 但未返回新 token，转 v1 重试")
    else:
        print(f"[INFO] v2 不可用：code={payload.get('code')} msg={str(payload.get('msg'))[:200]}")

    print(f"[2/2] 回落 drive v1 复制接口 …")
    folder_token = args.folder_token
    if not folder_token:
        print("[..] 未指定文件夹，取应用云空间根目录后创建「JobHunter 模板」文件夹 …")
        payload_root = api("GET", "/drive/explorer/v2/root_folder/meta")
        root_token = payload_root.get("data", {}).get("token", "") if payload_root.get("code") == 0 else ""
        if not root_token:
            die(f"获取应用根文件夹失败：{payload_root.get('code')} {str(payload_root.get('msg'))[:200]}")
        print(f"[..] 应用根文件夹：{root_token}")
        payload_folder = api(
            "POST", "/drive/v1/files/create_folder",
            {"name": "JobHunter 模板", "folder_token": root_token},
        )
        print(f"[..] create_folder：code={payload_folder.get('code')} msg={str(payload_folder.get('msg'))[:120]}")
        if payload_folder.get("code") != 0:
            die("创建目标文件夹失败（可用 --folder-token 指定一个应用可编辑的文件夹后重试）")
        folder_token = payload_folder.get("data", {}).get("token", "")
        print(f"[..] 目标文件夹：{folder_token}")
    payload = api(
        "POST",
        f"/drive/v1/files/{PROD_APP_TOKEN}/copy",
        {"name": name, "type": "bitable", "folder_token": folder_token},
        params={"type": "bitable"},
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2)[:1500])
    if payload.get("code") != 0:
        die("v1 复制也失败：按报错补权限/发版本后再试（提示：飞书权限变更必须「创建版本并发布」才生效）")
    data = payload.get("data", {})
    file_info = data.get("file") or {}
    new_token = data.get("token") or file_info.get("token") or ""
    new_url = data.get("url") or file_info.get("url") or ""
    ticket = data.get("ticket") or ""
    if not new_token and ticket:
        die(f"复制转为异步任务 ticket={ticket}，请稍后用 inspect 手动确认新副本后回填 {STATE_PATH}")
    if not new_token:
        die("复制响应里没有新 token，原样输出见上")
    write_state({"copy_app_token": new_token, "prod_app_token": PROD_APP_TOKEN, "copy_url": new_url})
    print(f"[OK] 复制成功：{new_token}")


def cmd_inspect_copy(args: argparse.Namespace) -> None:
    app = require_copy_app(args)
    print_tables(app, "模板副本")


def cmd_clean(args: argparse.Namespace) -> None:
    app = require_copy_app(args)
    require_yes(args, "clean（清空记录）")
    for table_id in args.table:
        ids = list_record_ids(app, table_id)
        print(f"[clean] {table_id}：{len(ids)} 条记录待删除")
        deleted = 0
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            payload = api(
                "POST",
                f"/bitable/v1/apps/{app}/tables/{table_id}/records/batch_delete",
                {"records": chunk},
            )
            if payload.get("code") != 0:
                die(f"batch_delete 失败（{table_id} @{i}）：{payload.get('code')} {payload.get('msg')}")
            deleted += len(chunk)
            print(f"  已删 {deleted}/{len(ids)}")
            time.sleep(0.35)
        remain = len(list_record_ids(app, table_id))
        print(f"[clean] {table_id} 完成，剩余 {remain} 条")
        if remain:
            die(f"{table_id} 删后仍有残留，中止后续步骤")


def cmd_delete_table(args: argparse.Namespace) -> None:
    app = require_copy_app(args)
    target = next((t for t in list_tables(app) if t["table_id"] == args.table), None)
    if target is None:
        die(f"副本里找不到表 {args.table}")
    name = target.get("name", "")
    if args.expect_name:
        if args.expect_name not in name:
            die(f"表名校验失败：期望含「{args.expect_name}」，实际「{name}」")
    else:
        print(f"[WARN] 未传 --expect-name，跳过表名核对，目标表名「{name}」")
    require_yes(args, "delete-table（删整张表）")
    payload = api("DELETE", f"/bitable/v1/apps/{app}/tables/{args.table}")
    if payload.get("code") != 0:
        die(f"删除表失败：{payload.get('code')} {payload.get('msg')}")
    print(f"[delete-table] 已删除：{name}（{args.table}）")


# 示例行：明显虚构，字段与实际表字段求交集后才写；单选值不在选项里则按偏好列表降级
EXAMPLE_ROWS: list[dict] = [
    {
        "岗位名称": "资深Python后端工程师（示例）",
        "公司名称": "示例公司A（演示数据）",
        "城市": "示例市",
        "薪资": "25K-35K·15薪（示例）",
        "跟进状态": ["新线索", "待评估", "待投递"],
        "岗位链接": "https://example.com/job-a",
        "经验要求": "3-5年（示例）",
        "公司规模": "100-499人（示例）",
    },
    {
        "岗位名称": "AI应用开发工程师（示例）",
        "公司名称": "示例公司B（演示数据）",
        "城市": "示例市",
        "薪资": "20K-30K（示例）",
        "跟进状态": ["待评估", "新线索", "待投递"],
        "岗位链接": "https://example.com/job-b",
        "经验要求": "1-3年（示例）",
        "公司规模": "50-99人（示例）",
    },
    {
        "岗位名称": "数据分析师（示例）",
        "公司名称": "示例公司C（演示数据）",
        "城市": "示例市",
        "薪资": "15K-25K（示例）",
        "跟进状态": ["待投递", "新线索", "待评估"],
        "岗位链接": "https://example.com/job-c",
        "经验要求": "1-3年（示例）",
        "公司规模": "1000-9999人（示例）",
    },
]

# 类型常量（飞书字段 type）：1文本 2数字 3单选 4多选 15链接；其余类型一律静默跳过


def _pick_option(field: dict, preferences: list[str]) -> str | None:
    options = [o.get("name", "") for o in (field.get("property") or {}).get("options", [])]
    for want in preferences:
        if want in options:
            return want
    return None


def cmd_examples(args: argparse.Namespace) -> None:
    app = require_copy_app(args)
    require_yes(args, "examples（写示例行）")
    tables = list_tables(app)
    jobs = next((t for t in tables if t.get("name") == "岗位数据汇总表"), None)
    if jobs is None:
        die("副本里找不到「岗位数据汇总表」，请 inspect-copy 核对表名")
    tid = jobs["table_id"]

    fields: dict = {}
    page_token = ""
    while True:
        params: dict = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        payload = api("GET", f"/bitable/v1/apps/{app}/tables/{tid}/fields", params=params)
        if payload.get("code") != 0:
            die(f"读字段失败：{payload.get('code')} {payload.get('msg')}")
        data = payload.get("data", {})
        for f in data.get("items", []):
            fields[f["field_name"]] = f
        if not data.get("has_more"):
            break
        page_token = data.get("page_token", "")
    print(f"[examples] 岗位表共 {len(fields)} 个字段")

    records = []
    for row in EXAMPLE_ROWS:
        fields_payload: dict = {}
        for key, value in row.items():
            field = fields.get(key)
            if field is None:
                print(f"  [skip] 字段不存在：{key}")
                continue
            ftype = field["type"]
            if ftype == 1:
                fields_payload[key] = value
            elif ftype == 2:
                continue  # 示例值非纯数字，跳过
            elif ftype == 3:
                picked = _pick_option(field, value if isinstance(value, list) else [value])
                if picked:
                    fields_payload[key] = picked
                else:
                    print(f"  [skip] 单选无可用选项：{key}")
            elif ftype == 4:
                picked = _pick_option(field, value if isinstance(value, list) else [value])
                if picked:
                    fields_payload[key] = [picked]
                else:
                    print(f"  [skip] 多选无可用选项：{key}")
            elif ftype == 15:
                fields_payload[key] = {"link": value, "text": value}
        records.append({"fields": fields_payload})

    payload = api(
        "POST",
        f"/bitable/v1/apps/{app}/tables/{tid}/records/batch_create",
        {"records": records},
    )
    if payload.get("code") != 0:
        die(f"batch_create 失败：{payload.get('code')} {payload.get('msg')}")
    count = len(list_record_ids(app, tid))
    print(f"[examples] 写入完成，岗位表现有 {count} 条（应为 3）")
    if count != 3:
        die("示例行数量与预期不符，请人工检查")


def cmd_chat_members(args: argparse.Namespace) -> None:
    items: list[dict] = []
    page_token = ""
    while True:
        params: dict = {"member_id_type": "open_id", "page_size": 100}
        if page_token:
            params["page_token"] = page_token
        payload = api("GET", f"/im/v1/chats/{args.chat_id}/members", params=params)
        if payload.get("code") != 0:
            die(f"列群成员失败：{payload.get('code')} {payload.get('msg')}")
        data = payload.get("data", {})
        items.extend(data.get("items", []))
        if not data.get("has_more"):
            break
        page_token = data.get("page_token", "")
    print(f"[chat-members] 共 {len(items)} 名成员：")
    resolved = []
    for i, m in enumerate(items):
        oid = m.get("member_id", "")
        print(f"  [{i}] {m.get('name', '?')}  {oid[:8]}...{oid[-4:]}")
        resolved.append({"name": m.get("name", ""), "open_id": oid})
    write_state({"chat_members": resolved})


def cmd_add_collaborator(args: argparse.Namespace) -> None:
    app = require_copy_app(args)
    require_yes(args, "add-collaborator（加协作者）")
    members = read_state().get("chat_members", [])
    if not members:
        die("状态文件里没有群成员列表，请先跑 chat-members")
    if args.pick is None or not (0 <= args.pick < len(members)):
        die(f"--pick 需为 0..{len(members) - 1} 的下标（先跑 chat-members）")
    member = members[args.pick]
    payload = api(
        "POST",
        f"/drive/v1/permissions/{app}/members",
        {"member_type": "openid", "member_id": member["open_id"], "perm": "full_access"},
        params={"type": "bitable", "need_notification": "true"},
    )
    if payload.get("code") != 0:
        die(f"加协作者失败：{payload.get('code')} {payload.get('msg')}")
    print(f"[add-collaborator] 已把 {member['name']} 加为副本 full_access 协作者（飞书应已收到通知）")


def cmd_set_public(args: argparse.Namespace) -> None:
    app = require_copy_app(args)
    require_yes(args, "set-public（公开分享）")
    body = {
        "external_access_entity": "open",
        "security_entity": "anyone_can_view",
        "comment_entity": "anyone_can_view",
        "share_entity": "anyone",
        "manage_collaborator_entity": "collaborator_can_view",
        "link_share_entity": "anyone_readable",
        "copy_entity": "anyone_can_view",
        "creator_setting": {"share_entity": "anyone"},
    }
    payload = api("PATCH", f"/drive/v1/permissions/{app}/public", body, params={"type": "bitable"})
    if payload.get("code") != 0:
        print(f"[WARN] 全量设置失败：{payload.get('code')} {payload.get('msg')}，改用最小参数重试")
        payload = api(
            "PATCH",
            f"/drive/v1/permissions/{app}/public",
            {"external_access_entity": "open", "link_share_entity": "anyone_readable"},
            params={"type": "bitable"},
        )
        if payload.get("code") != 0:
            die(f"set-public 失败：{payload.get('code')} {payload.get('msg')}")
    check = api("GET", f"/drive/v1/permissions/{app}/public", params={"type": "bitable"})
    print("[set-public] 当前公开设置：")
    print(json.dumps(check.get("data", {}), ensure_ascii=False, indent=2))
    print(f"[set-public] 模板链接：https://feishu.cn/base/{app}")


def cmd_verify(args: argparse.Namespace) -> None:
    app = require_copy_app(args)
    state = read_state()
    print(f"副本 app_token：{app}")
    print(f"副本链接：{state.get('copy_url') or f'https://feishu.cn/base/{app}'}")
    print_tables(app, "模板副本")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("inspect", help="只读：生产 Base 表清单")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("copy", help="复制生产 Base 为模板副本")
    p.add_argument("--name", default="Auto-JobHunter 求职中枢模板")
    p.add_argument("--folder-token", default="", help="目标文件夹；缺省时自动在应用根目录创建「JobHunter 模板」")
    p.set_defaults(func=cmd_copy)

    p = sub.add_parser("inspect-copy", help="只读：副本表清单")
    p.add_argument("--app-token", default="")
    p.set_defaults(func=cmd_inspect_copy)

    p = sub.add_parser("clean", help="清空指定表全部记录")
    p.add_argument("--table", action="append", required=True)
    p.add_argument("--app-token", default="")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_clean)

    p = sub.add_parser("delete-table", help="删除整张表")
    p.add_argument("--table", required=True)
    p.add_argument("--expect-name", default="")
    p.add_argument("--app-token", default="")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_delete_table)

    p = sub.add_parser("examples", help="写入 3 条虚构示例行")
    p.add_argument("--app-token", default="")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_examples)

    p = sub.add_parser("chat-members", help="列出 ChatOps 群成员")
    p.add_argument("--chat-id", required=True)
    p.set_defaults(func=cmd_chat_members)

    p = sub.add_parser("add-collaborator", help="把用户加为副本协作者")
    p.add_argument("--pick", type=int, default=None)
    p.add_argument("--app-token", default="")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_add_collaborator)

    p = sub.add_parser("set-public", help="公开分享（等脱敏确认后再跑）")
    p.add_argument("--app-token", default="")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_set_public)

    p = sub.add_parser("verify", help="只读：复核副本")
    p.add_argument("--app-token", default="")
    p.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
