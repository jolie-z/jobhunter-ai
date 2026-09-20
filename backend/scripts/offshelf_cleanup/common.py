"""
已下架岗位清理 — 公共工具层（飞书 API / 运行数据 / 浏览器基建）。

只依赖 requests + 项目 registry/browser，不 import app.main（避免 DB/APScheduler 副作用）。
"""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import requests

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = BACKEND_ROOT / "data" / "offshelf_cleanup"
DATA_DIR.mkdir(parents=True, exist_ok=True)

RECORDS_FILE = DATA_DIR / "records.json"          # 飞书岗位表全量快照（含完整 fields）
CHECK_FILE = DATA_DIR / "check_results.jsonl"      # 验活结果断点文件（逐条追加）
ARCHIVE_META = DATA_DIR / "archive_table.json"     # 归档表 table_id 等元数据
MOVE_LOG = DATA_DIR / "move_log.jsonl"             # 搬移日志（逐批追加）

# 跟进状态语义
STATUS_APPLIED = "已投递"     # 无条件保留
STATUS_OFFSHELF = "已下架"    # BOSS 预检已确认死亡，无需再查，直接归档
# 参与验活的四个平台（小红书不在本次范围）
SCOPE_PLATFORMS = ["BOSS直聘", "猎聘", "51job", "智联招聘"]
PLATFORM_KEY = {  # 飞书「招聘平台」取值 → registry 规范名
    "BOSS直聘": "boss",
    "猎聘": "liepin",
    "51job": "51job",
    "智联招聘": "zhilian",
}
# 只读字段类型（创建时间/修改时间/创建人/修改人/自动编号），归档复制时须剔除
READONLY_FIELD_TYPES = {1001, 1002, 1003, 1004, 1005}

FEISHU_API = "https://open.feishu.cn/open-apis"


# ---------------------------------------------------------------- .env / token

def load_env() -> dict:
    vals = {}
    env_path = BACKEND_ROOT / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


_ENV = load_env()


def _cfg(key: str) -> str:
    value = _ENV.get(key)
    if not value:
        raise SystemExit(f".env 缺少配置项: {key}")
    return value


APP_ID = _cfg("FEISHU_APP_ID")
globals()["APP_SECRET"] = _cfg("FEISHU_APP_SECRET")
globals()["APP_TOKEN"] = _cfg("FEISHU_APP_TOKEN")
JOBS_TABLE_ID = _cfg("FEISHU_TABLE_ID_JOBS")

_token_cache = {"token": None, "expire_at": 0}


def get_token() -> str:
    if _token_cache["token"] and time.time() < _token_cache["expire_at"] - 300:
        return _token_cache["token"]
    resp = requests.post(
        f"{FEISHU_API}/auth/v3/tenant_access_token/internal",
        json={"app_id": APP_ID, "app_secret": APP_SECRET},
        timeout=15,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败: {data}")
    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expire_at"] = time.time() + data.get("expire", 7200)
    return _token_cache["token"]


def _headers():
    return {"Authorization": f"Bearer {get_token()}", "Content-Type": "application/json"}


def _request_with_retry(method: str, url: str, retries: int = 4, **kwargs):
    """飞书 API 调用，带限流退避重试。返回解析后的 JSON；code!=0 时抛出。"""
    for attempt in range(retries):
        resp = requests.request(method, url, headers=_headers(), timeout=60, **kwargs)
        if resp.status_code == 429:
            time.sleep(2 * (attempt + 1))
            continue
        data = resp.json()
        code = data.get("code")
        if code == 0:
            return data
        if code in (1254607, 99991400, 99991401, 1254045):  # 限流/频率类
            time.sleep(2 * (attempt + 1))
            continue
        raise RuntimeError(f"飞书 API 失败 [{code}] {data.get('msg')} url={url}")
    raise RuntimeError(f"飞书 API 重试耗尽: {url}")


# ---------------------------------------------------------------- 记录读写

def normalize_text(value) -> str:
    """把飞书字段值归一成纯文本（兼容 富文本段列表/多选列表/字符串/None）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "".join(parts).strip()
    if isinstance(value, dict):
        return str(value.get("text", "")).strip()
    return str(value)


def extract_link(fields: dict) -> str:
    link_field = fields.get("岗位链接")
    if isinstance(link_field, dict):
        return link_field.get("link", "") or ""
    if isinstance(link_field, str):
        return link_field
    return ""


def fetch_all_records() -> list:
    """全量翻页拉取岗位表记录（GET /records），返回 [{record_id, fields}]。"""
    records = []
    page_token = None
    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        data = _request_with_retry(
            "GET", f"{FEISHU_API}/bitable/v1/apps/{APP_TOKEN}/tables/{JOBS_TABLE_ID}/records",
            params=params,
        )
        items = data.get("data", {}).get("items") or []
        records.extend(items)
        has_more = data.get("data", {}).get("has_more")
        page_token = data.get("data", {}).get("page_token")
        print(f"  已拉取 {len(records)} 条 ...", flush=True)
        if not has_more or not page_token:
            break
        time.sleep(0.2)
    return records


def save_records_snapshot(records: list):
    slim = []
    for r in records:
        fields = r.get("fields") or {}
        slim.append({
            "record_id": r["record_id"],
            "platform": normalize_text(fields.get("招聘平台")),
            "status": normalize_text(fields.get("跟进状态")),
            "link": extract_link(fields),
            "job_name": normalize_text(fields.get("岗位名称")),
            "company": normalize_text(fields.get("公司名称")),
            "fields": fields,  # 完整字段，供归档原样复制
        })
    RECORDS_FILE.write_text(json.dumps(slim, ensure_ascii=False), encoding="utf-8")
    return slim


def load_records() -> list:
    if not RECORDS_FILE.exists():
        raise SystemExit("records.json 不存在，请先运行: offshelf.py fetch")
    return json.loads(RECORDS_FILE.read_text(encoding="utf-8"))


def load_check_results() -> dict:
    results = {}
    if CHECK_FILE.exists():
        for line in CHECK_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            results[item["record_id"]] = item
    return results


def append_check_result(item: dict):
    with CHECK_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- 表结构 / 归档表

def list_fields(table_id: str) -> list:
    fields, page_token = [], None
    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        data = _request_with_retry(
            "GET", f"{FEISHU_API}/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/fields",
            params=params,
        )
        fields.extend(data.get("data", {}).get("items") or [])
        if not data.get("data", {}).get("has_more"):
            break
        page_token = data.get("data", {}).get("page_token")
    return fields


def list_tables() -> list:
    tables, page_token = [], None
    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        data = _request_with_retry(
            "GET", f"{FEISHU_API}/bitable/v1/apps/{APP_TOKEN}/tables", params=params,
        )
        tables.extend(data.get("data", {}).get("items") or [])
        if not data.get("data", {}).get("has_more"):
            break
        page_token = data.get("data", {}).get("page_token")
    return tables


def _sanitize_property(prop: dict) -> dict:
    """字段属性清洗：单选/多选的 option id 只在原表有效，镜像时必须剥掉。"""
    if not isinstance(prop, dict):
        return prop
    cleaned = dict(prop)
    options = cleaned.get("options")
    if isinstance(options, list):
        new_options = []
        for opt in options:
            if isinstance(opt, dict):
                opt = {k: v for k, v in opt.items() if k != "id"}
            new_options.append(opt)
        cleaned["options"] = new_options
    return cleaned


# 归档表白名单字段（岗位身份 + 审计所需）；公式(20)/经纬度(22)/记录链接(18)等类型无法跨表镜像
ARCHIVE_FIELD_WHITELIST = [
    "公司名称", "岗位名称", "城市", "岗位链接", "薪资", "招聘平台",
    "岗位详情", "公司规模", "所属行业", "学历要求", "经验要求",
    "发布日期", "抓取时间", "跟进状态", "综合评级 (A-F)", "投递日期",
]


def create_archive_table(name: str = "已下架归档") -> str:
    """在同一本多维表格下创建白名单字段归档表；已存在同名表则直接复用。"""
    for t in list_tables():
        if t.get("name") == name:
            print(f"归档表已存在，复用: {t['table_id']}")
            return t["table_id"]

    src_by_name = {f["field_name"]: f for f in list_fields(JOBS_TABLE_ID)}
    mirror = []
    for idx, field_name in enumerate(ARCHIVE_FIELD_WHITELIST):
        f = src_by_name.get(field_name)
        if f is None:
            print(f"  警告：原表无字段「{field_name}」，跳过")
            continue
        item = {"field_name": f["field_name"], "type": f["type"]}
        if idx == 0:
            item["is_primary"] = True
        prop = f.get("property")
        if prop:
            item["property"] = _sanitize_property(prop)
        mirror.append(item)
    # 追加审计字段
    mirror.append({"field_name": "归档时间", "type": 1})
    mirror.append({"field_name": "归档原因", "type": 1})

    data = _request_with_retry(
        "POST", f"{FEISHU_API}/bitable/v1/apps/{APP_TOKEN}/tables",
        json={"table": {"name": name, "fields": mirror}},
    )
    table_id = data["data"]["table_id"]
    print(f"已创建归档表「{name}」: {table_id}（镜像 {len(mirror)} 个字段）")
    return table_id


def batch_create_records(table_id: str, records_fields: list) -> list:
    """批量创建（≤500/次），返回新建 record_id 列表。"""
    data = _request_with_retry(
        "POST", f"{FEISHU_API}/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/batch_create",
        json={"records": [{"fields": f} for f in records_fields]},
    )
    return [r["record_id"] for r in data["data"]["records"]]


def batch_delete_records(table_id: str, record_ids: list):
    """批量删除（≤500/次）。"""
    return _request_with_retry(
        "POST", f"{FEISHU_API}/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/batch_delete",
        json={"records": record_ids},
    )


# ---------------------------------------------------------------- 浏览器基建

def probe_port(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.5):
            return True
    except OSError:
        return False


def ensure_page_tab(port: int) -> None:
    """DrissionPage 接管要求至少一个 type=page 的标签页；
    浏览器只剩 edge://newtab（type=other）时会被拒连，这里先用 CDP 补开一个。"""
    try:
        resp = requests.get(f"http://127.0.0.1:{port}/json", timeout=5)
        tabs = resp.json()
        if any(t.get("type") == "page" for t in tabs):
            return
        # 新版 Chrome PUT /json/new，旧版 GET
        for method in ("put", "get"):
            try:
                r = requests.request(method, f"http://127.0.0.1:{port}/json/new?about:blank", timeout=5)
                if r.status_code == 200:
                    print(f"[{port}] 无 page 标签页，已通过 CDP 补开一个", flush=True)
                    return
            except Exception:
                continue
        print(f"[{port}] 警告：无法补开标签页，接管可能失败", flush=True)
    except Exception:
        pass


def ensure_browser(platform_key: str) -> None:
    """确保平台浏览器在监听；不在则按 registry 配置拉起并等待。"""
    sys.path.insert(0, str(BACKEND_ROOT))
    from app.session.registry import resolve_platform
    from app.session.browser import launch_edge

    config = resolve_platform(platform_key)
    if config is None:
        raise SystemExit(f"registry 中无平台配置: {platform_key}")
    if not probe_port(config.port):
        print(f"[{platform_key}] 浏览器未监听 {config.port}，正在拉起 ...", flush=True)
        launch_edge(config)
        for _ in range(30):
            time.sleep(1)
            if probe_port(config.port):
                print(f"[{platform_key}] 已就绪 :{config.port}", flush=True)
                break
        else:
            raise RuntimeError(f"[{platform_key}] 浏览器 30 秒内未就绪")
    ensure_page_tab(config.port)
