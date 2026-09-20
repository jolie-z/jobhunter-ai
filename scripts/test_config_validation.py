"""
底层配置模块验证脚本
====================
系统性验证 .env 中所有关键密钥/配置是否真正生效。

验证分组（按业务重要性）：
1. 飞书开放平台（核心：岗位表、简历库、消息推送）
2. LLM 大模型（核心：评估/改写/清洗）
3. 搜索服务（Serper/Tavily：公司背调）
4. 数据库（PostgreSQL + SQLite）
5. 其他（高德地图、火山 ASR 等，非阻塞）

用法：python test_config_validation.py [--group feishu|llm|search|db|all]
"""
import os
import sys
import json

# 从 backend 目录加载
BACKEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)  # 确保 load_dotenv 能找到 .env

# 🌟 显式加载 backend/.env，确保 USE_MAIN_LLM_FOR_CLEANER 等开关生效
from dotenv import load_dotenv
load_dotenv(os.path.join(BACKEND_DIR, ".env"), override=False)

from app.core.config import settings

# 结果收集
RESULTS = []


def record(group, name, ok, detail=""):
    icon = "✅" if ok else "❌"
    RESULTS.append({"group": group, "name": name, "ok": ok, "detail": detail})
    print(f"  {icon} {name}: {detail}")


def section(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


# ==========================================
# 1. 飞书开放平台验证
# ==========================================
def check_feishu():
    section("1️⃣  飞书开放平台（FEISHU）")

    # 1.1 配置项存在性
    app_id = settings.FEISHU_APP_ID
    app_secret = settings.FEISHU_APP_SECRET
    app_token = settings.FEISHU_APP_TOKEN
    if not app_id or not app_secret:
        record("feishu", "App 凭证配置", False, "FEISHU_APP_ID / FEISHU_APP_SECRET 缺失")
        return
    record("feishu", "App 凭证配置", True, "APP_ID/SECRET 已配置")

    # 1.2 获取 tenant_access_token（验证凭证真实性）
    try:
        import requests
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        resp = requests.post(url, json={"app_id": app_id, "app_secret": app_secret},
                             timeout=15, proxies={"http": None, "https": None})
        data = resp.json()
        if data.get("code") == 0:
            token = data.get("tenant_access_token", "")
            record("feishu", "tenant_access_token 获取", True, f"凭证有效，token 前缀 {token[:8]}***")
        else:
            record("feishu", "tenant_access_token 获取", False, f"code={data.get('code')} msg={data.get('msg')}")
            return
    except Exception as e:
        record("feishu", "tenant_access_token 获取", False, f"请求异常: {e}")
        return

    # 1.3 验证多维表格访问（岗位表）
    table_id = settings.FEISHU_TABLE_ID_JOBS
    if not app_token or not table_id:
        record("feishu", "岗位多维表格配置", False, "FEISHU_APP_TOKEN / FEISHU_TABLE_ID_JOBS 缺失")
    else:
        try:
            url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/search"
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            resp = requests.post(url, headers=headers, json={"page_size": 1},
                                 timeout=15, proxies={"http": None, "https": None})
            data = resp.json()
            if data.get("code") == 0:
                total = data.get("data", {}).get("total", 0)
                record("feishu", "岗位多维表格访问", True, f"可访问，共 {total} 条记录")
            else:
                record("feishu", "岗位多维表格访问", False, f"code={data.get('code')} msg={data.get('msg')}")
        except Exception as e:
            record("feishu", "岗位多维表格访问", False, f"请求异常: {e}")

    # 1.4 验证简历库表格
    resume_table = settings.FEISHU_TABLE_ID_RESUMES
    if not resume_table:
        record("feishu", "简历库表格配置", False, "FEISHU_TABLE_ID_RESUMES 缺失")
    else:
        try:
            url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{resume_table}/records/search"
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            resp = requests.post(url, headers=headers, json={"page_size": 1},
                                 timeout=15, proxies={"http": None, "https": None})
            data = resp.json()
            if data.get("code") == 0:
                total = data.get("data", {}).get("total", 0)
                record("feishu", "简历库表格访问", True, f"可访问，共 {total} 条简历")
            else:
                record("feishu", "简历库表格访问", False, f"code={data.get('code')} msg={data.get('msg')}")
        except Exception as e:
            record("feishu", "简历库表格访问", False, f"请求异常: {e}")


# ==========================================
# 2. LLM 大模型验证
# ==========================================
def _test_llm_endpoint(name, api_key, base_url, model, max_tokens=1000):
    """通用 LLM 连通性测试：发一个最简单的补全请求"""
    if not api_key:
        record("llm", name, False, "API_KEY 缺失")
        return
    if not model:
        record("llm", name, False, "MODEL 未配置")
        return
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "请简短回复：配置正常"}],
            max_tokens=max_tokens,  # 推理模型需要足够的 token 空间输出 content
            timeout=60,
        )
        content = (resp.choices[0].message.content or "").strip()
        if content:
            record("llm", name, True, f"模型 {model} 响应正常: '{content[:20]}'")
        else:
            # 推理模型可能把 token 花在 reasoning_content 上
            reasoning = getattr(resp.choices[0].message, 'reasoning_content', None)
            if reasoning:
                record("llm", name, False, f"模型 {model} 返回空 content（推理模型需调大 max_tokens）")
            else:
                record("llm", name, False, f"模型 {model} 返回空内容")
    except Exception as e:
        record("llm", name, False, f"调用失败: {str(e)[:120]}")


def check_llm():
    section("2️⃣  LLM 大模型（评估/改写/清洗核心）")
    _test_llm_endpoint("主 LLM (OPENAI)", settings.OPENAI_API_KEY, settings.OPENAI_BASE_URL, settings.OPENAI_MODEL)

    # 清洗 LLM：检查 USE_MAIN_LLM_FOR_CLEANER 开关
    use_main = os.getenv("USE_MAIN_LLM_FOR_CLEANER", "").strip() in ("1", "true", "yes")
    if use_main:
        record("llm", "清洗 LLM (CLEANER)", True, "已启用 USE_MAIN_LLM_FOR_CLEANER=1，清洗功能将使用主 LLM 通道")
    else:
        _test_llm_endpoint("清洗 LLM (CLEANER)", settings.CLEANER_LLM_API_KEY, settings.CLEANER_LLM_BASE_URL, settings.CLEANER_LLM_MODEL)


# ==========================================
# 3. 搜索服务验证（公司背调）
# ==========================================
def check_search():
    section("3️⃣  搜索服务（公司背调）")

    # Serper（公司情报主引擎，settings.json / 环境变量均可）
    from common.config import get_serper_api_key
    serper_key = get_serper_api_key()
    if not serper_key:
        record("search", "Serper (Google 搜索)", False, "SERPER_API_KEY 缺失，公司情报将降级 Tavily（可在设置页「搜索/情报」填写）")
    else:
        try:
            import requests
            resp = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                json={"q": "test", "num": 1},
                timeout=15,
            )
            if resp.status_code == 200:
                record("search", "Serper (Google 搜索)", True, "API 有效，可返回搜索结果")
            else:
                record("search", "Serper (Google 搜索)", False, f"HTTP {resp.status_code}: {resp.text[:80]}")
        except Exception as e:
            record("search", "Serper (Google 搜索)", False, f"请求异常: {e}")

    # Tavily（降级备用引擎，缺失不阻塞）
    tavily_key = settings.TAVILY_API_KEY
    if not tavily_key:
        record("search", "Tavily", True, "TAVILY_API_KEY 缺失（仅降级备用引擎，不影响主链路）")
    else:
        try:
            import requests
            resp = requests.post(
                "https://api.tavily.com/search",
                json={"api_key": tavily_key, "query": "test", "max_results": 1},
                timeout=15,
            )
            if resp.status_code == 200:
                record("search", "Tavily", True, "API 有效")
            else:
                record("search", "Tavily", False, f"HTTP {resp.status_code}: {resp.text[:80]}")
        except Exception as e:
            record("search", "Tavily", False, f"请求异常: {e}")


# ==========================================
# 4. 数据库验证
# ==========================================
def check_database():
    section("4️⃣  数据库（PostgreSQL + SQLite）")

    # PostgreSQL（懒连接，未运行不阻塞启动；项目未配置时优雅跳过）
    if not hasattr(settings, "POSTGRES_SERVER"):
        record("db", "PostgreSQL 连接", True, "未配置 POSTGRES_*（项目以 SQLite 为主，已跳过）")
    else:
        try:
            import psycopg
            conn_str = (
                f"host={settings.POSTGRES_SERVER} port={settings.POSTGRES_PORT} "
                f"user={settings.POSTGRES_USER} password={settings.POSTGRES_PASSWORD} "
                f"dbname={settings.POSTGRES_DB} connect_timeout=8"
            )
            conn = psycopg.connect(conn_str)
            cur = conn.execute("SELECT version()")
            version = cur.fetchone()[0][:40]
            conn.close()
            record("db", "PostgreSQL 连接", True, f"连接成功: {version}...")
        except Exception as e:
            record("db", "PostgreSQL 连接", False, f"连接失败（项目用 SQLite 为主，PostgreSQL 未运行不阻塞启动）: {str(e)[:60]}")

    # SQLite（岗位主库）—— 优先检查 backend/data 下的路径
    sqlite_path = os.path.join(BACKEND_DIR, "data", "job_hunter.db")
    if not os.path.exists(sqlite_path):
        alt_path = os.path.join(os.path.dirname(BACKEND_DIR), "data", "job_hunter.db")
        if os.path.exists(alt_path):
            sqlite_path = alt_path
    if os.path.exists(sqlite_path):
        try:
            import sqlite3
            conn = sqlite3.connect(sqlite_path)
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            # 统计岗位数
            job_count = 0
            if "raw_jobs" in tables:
                job_count = conn.execute("SELECT COUNT(*) FROM raw_jobs").fetchone()[0]
            conn.close()
            detail = f"路径存在，含 {len(tables)} 张表"
            if job_count:
                detail += f"，raw_jobs 岗位数: {job_count}"
            record("db", "SQLite 岗位库", True, detail)
        except Exception as e:
            record("db", "SQLite 岗位库", False, f"读取失败: {e}")
    else:
        record("db", "SQLite 岗位库", False, f"文件不存在: {sqlite_path}")


# ==========================================
# 5. 其他服务（非阻塞）
# ==========================================
def check_others():
    section("5️⃣  其他服务（非核心，缺失不阻塞）")

    # 高德地图：真实调用地理编码 API 验证
    if settings.AMAP_API_KEY:
        try:
            import requests
            resp = requests.get(
                settings.AMAP_BASE_URL or "https://restapi.amap.com/v3/geocode/geo",
                params={"address": "广州市天河区", "key": settings.AMAP_API_KEY},
                timeout=15,
            )
            data = resp.json()
            if data.get("status") == "1" and data.get("geocodes"):
                record("other", "高德地图 (AMAP)", True, f"API 有效，地理编码实测通过")
            else:
                record("other", "高德地图 (AMAP)", False, f"API 返回异常: {data.get('info')} (code {data.get('infocode')})")
        except Exception as e:
            record("other", "高德地图 (AMAP)", False, f"请求异常: {e}")
    else:
        record("other", "高德地图 (AMAP)", False, "AMAP_API_KEY 缺失（非阻塞）")

    if settings.VOLC_ASR_APPID and settings.VOLC_ASR_TOKEN:
        record("other", "火山 ASR 语音识别", True, "已配置（未做在线验证）")
    else:
        record("other", "火山 ASR 语音识别", False, "VOLC_ASR 配置不全（非阻塞）")


# ==========================================
# 主入口
# ==========================================
def main():
    group = sys.argv[1] if len(sys.argv) > 1 else "all"

    print("\n🔍 JobHunter 底层配置验证")
    print(f"   ENVIRONMENT: {settings.ENVIRONMENT}")
    print(f"   PROJECT_NAME: {settings.PROJECT_NAME}")

    checks = {
        "feishu": check_feishu,
        "llm": check_llm,
        "search": check_search,
        "db": check_database,
        "other": check_others,
    }

    if group == "all":
        for fn in checks.values():
            fn()
    elif group in checks:
        checks[group]()
    else:
        print(f"未知分组: {group}，可选: {list(checks.keys())} 或 all")
        return

    # 汇总
    section("📊 验证汇总")
    ok_count = sum(1 for r in RESULTS if r["ok"])
    fail_count = len(RESULTS) - ok_count
    print(f"  总计: {len(RESULTS)} 项 | ✅ 通过: {ok_count} | ❌ 失败: {fail_count}")
    if fail_count:
        print("\n  ⚠️ 失败项明细:")
        for r in RESULTS:
            if not r["ok"]:
                print(f"    ❌ [{r['group']}] {r['name']}: {r['detail']}")


if __name__ == "__main__":
    main()
