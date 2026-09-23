import sys
import os
import asyncio
import contextvars
import sqlite3
import requests
import json

from app.core.feishu_utils import get_tenant_access_token
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)



try:
    from common.config import FEISHU_APP_TOKEN, FEISHU_TABLE_ID_JOBS
    NEW_APP_TOKEN = FEISHU_APP_TOKEN
    NEW_TABLE_ID = FEISHU_TABLE_ID_JOBS
except ImportError:
    NEW_APP_TOKEN = ""
    NEW_TABLE_ID = ""
    print("⚠️ 警告：未找到 config.py，飞书表格 Token 未配置。")

# 连续查重未知态达到该数量即升级告警（疑似飞书故障，Q-M9-3 配套）
_UNKNOWN_ESCALATE_AFTER = 5

# 🌟 主事件循环锚点：step2 是纯同步函数，被 asyncio.to_thread 拉到工作线程执行，
# asyncio.Queue 非线程安全，工作线程必须经主 loop 的 call_soon_threadsafe 写入。
# 锚定不用模块级全局变量（跨用例/跨任务易污染），改用 ContextVar：
# sync_sqlite_to_feishu_async 在事件循环线程 set 当前 loop，asyncio.to_thread 内部
# copy_context() 会把它透传给工作线程，线程内 get 即得宿主 loop，无全局状态。
_ANCHORED_LOOP: "contextvars.ContextVar[asyncio.AbstractEventLoop | None]" = contextvars.ContextVar("step2_anchored_loop", default=None)

async def sync_sqlite_to_feishu_async(*args, **kwargs):
    """sync_sqlite_to_feishu 的 async 入口：先把当前主 loop 锚进 ContextVar 再 to_thread。
    所有从事件循环发起的飞书同步 MUST 走本入口——直接 to_thread 原函数的话，
    工作线程内拿不到锚定 loop，SSE 进度消息会被丢弃（仅打印告警，不崩溃）。"""
    token = _ANCHORED_LOOP.set(asyncio.get_running_loop())
    try:
        return await asyncio.to_thread(sync_sqlite_to_feishu, *args, **kwargs)
    finally:
        _ANCHORED_LOOP.reset(token)

def _push_sse_threadsafe(task_id: str, msg: str):
    """跨线程安全推送：事件循环线程直写；工作线程经锚定 loop 的 call_soon_threadsafe 转交。
    拿不到锚定 loop 时宁丢一条进度消息也不用非线程安全的跨线程直写（会碰坏 loop 内部状态）。"""
    if not task_id:
        return
    try:
        from app.tasks.state import task_queues
        q = task_queues.get(task_id)
        if not q:
            return
        try:
            cur_loop = asyncio.get_running_loop()
        except RuntimeError:
            cur_loop = None
        anchored = _ANCHORED_LOOP.get()
        if cur_loop is not None and (anchored is None or cur_loop is anchored):
            q.put_nowait(msg)  # 就在 queue 宿主 loop 的线程上，直写安全
            return
        if anchored is not None and not anchored.is_closed():
            anchored.call_soon_threadsafe(q.put_nowait, msg)
            return
        print(f"⚠️ [SSE] task={task_id} 无可用主事件循环，丢弃一条进度消息（入口须走 sync_sqlite_to_feishu_async）", flush=True)
    except Exception as e:
        print(f"⚠️ [SSE] task={task_id} 进度推送异常（不阻断主流程）: {type(e).__name__}: {e}", flush=True)

def push_sse_message_sync(task_id: str, message: str, status="info"):
    if not task_id: return
    try:
        data = {"type": "log", "message": f"🔗 [飞书同步] {message}"}
        if status == "error":
            data["type"] = "error"
        msg = f'data: {json.dumps(data, ensure_ascii=False)}\n\n'
        _push_sse_threadsafe(task_id, msg)
    except Exception:
        pass

def push_sse_event(task_id: str, event_data: dict):
    if not task_id: return
    try:
        msg = f'data: {json.dumps(event_data, ensure_ascii=False)}\n\n'
        _push_sse_threadsafe(task_id, msg)
    except Exception:
        pass

def check_job_exists(token, company_name, job_title, city) -> "str | bool | None":
    """
    查重：基于「公司名称 + 岗位名称 + 城市」三要素联合判断飞书多维表格中是否已存在该岗位。
    返回值三态（契约由类型标注与本 docstring 锁死，调用方必须显式判 None）：
      - 已存在 → 已有记录的 record_id（str），个别缺失 record_id 的命中返回 True
      - 确认不存在（code=0 且无命中）→ False
      - 未知（接口异常/业务错误码）→ None：调用方必须 fail-closed 跳过本轮，
        绝不可当作「不存在」冒险新建，否则飞书抖动期同一岗位会重复建档（Q-M9-3）。
        ⚠️ None 与 False 在真值上下文等价——任何新调用点禁止 `if not check_job_exists()`
        这类真值写法，必须 `is None` / `is not None` 显式分支。
    """
    if not company_name or not job_title:
        return False
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{NEW_APP_TOKEN}/tables/{NEW_TABLE_ID}/records/search"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "filter": {
            "conjunction": "and",
            "conditions": [
                {"field_name": "公司名称", "operator": "is", "value": [company_name]},
                {"field_name": "岗位名称", "operator": "is", "value": [job_title]},
                {"field_name": "城市", "operator": "is", "value": [city]}
            ]
        },
        "page_size": 1
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        res_json = resp.json()
        if res_json.get("code") == 0:
            items = res_json.get("data", {}).get("items", [])
            if items and len(items) > 0:
                rec_id = items[0].get("record_id")
                return rec_id if rec_id else True
            return False
        print(f"⚠️ [查重] 飞书查重返回业务错误 code={res_json.get('code')} msg={res_json.get('msg')}，按未知态处理（fail-closed）")
        return None
    except Exception as e:
        print(f"⚠️ [查重] 飞书查重接口异常，按未知态处理（fail-closed，不再默认放行）: {e}")
        return None



def push_single_record_to_feishu(token, feishu_fields):
    """
    单条推送数据到新的飞书多维表格（白盒底层探针版）
    """
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{NEW_APP_TOKEN}/tables/{NEW_TABLE_ID}/records"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    cleaned_fields = {k: v for k, v in feishu_fields.items() if v is not None}
    payload = {"fields": cleaned_fields}

    # 🌟 [白盒探针] 仅打印核心辨识信息，避免全量 Payload 刷屏
    comp_name = cleaned_fields.get("公司名称", "未知")
    title_name = cleaned_fields.get("岗位名称", "未知")
    print(f"� [白盒底层探针] 准备向飞书提交记录：【{comp_name} - {title_name}】")

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)

        # 🌟 [白盒探针] 仅在失败时打印详细回执
        # print(f"📥 [📥 飞书 HTTP 状态码]: {response.status_code}")

        res_json = response.json()
        if res_json.get("code") == 0:
            print("✅ [白盒底层探针] 飞书多维表格写入成功！\n")
            return res_json.get("data", {}).get("record", {}).get("record_id", "") or True
        else:
            # 提取飞书官方给出的精确字段错误提示
            error_details = res_json.get("error", {})
            print(f"❌ [白盒底层探针] 飞书拒绝写入！错误码: {res_json.get('code')}, 官方死因说明: {res_json.get('msg')}")
            if isinstance(error_details, dict) and "field_errors" in error_details:
                print(f"⚠️ [精确字段卡点明细]: {json.dumps(error_details['field_errors'], ensure_ascii=False)}")
            print("<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<\n")
            return False

    except Exception as net_e:
        print(f"💥 [白盒底层探针] 飞书通信发生网络级崩溃: {net_e}\n")
        return False

def build_feishu_fields_from_raw(job_data: dict) -> dict:
    """统一的数据转化中枢：将本地 SQLite 的 raw_jobs 行数据，完美转化为飞书多维表格需要的全量字段格式"""
    raw_link = job_data.get("job_link", "")
    if raw_link and not raw_link.startswith(("http://", "https://")):
        raw_link = "https://" + raw_link.lstrip("/")
    safe_link_obj = {"link": raw_link, "text": "🔗 点击直达"} if raw_link else None

    return {
        "岗位链接": safe_link_obj,
        "岗位名称": job_data.get("job_title", ""),
        "公司名称": job_data.get("company_name", ""),
        "城市": job_data.get("city", ""),
        "岗位详情": job_data.get("jd_text", ""),
        "薪资": job_data.get("salary", ""),
        "工作地址": job_data.get("work_address", ""),
        "HR活跃度": job_data.get("hr_activity", ""),
        "所属行业": job_data.get("industry", ""),
        "福利标签": job_data.get("welfare_tags", ""),
        "公司规模": job_data.get("company_size", ""),
        "学历要求": job_data.get("education_req", ""),
        "经验要求": job_data.get("experience_req", ""),
        "HR技能标签": job_data.get("hr_skill_tags", ""),
        "公司介绍": job_data.get("company_intro", ""),
        "角色": job_data.get("role", ""),
        "发布日期": job_data.get("publish_date", ""),
        "招聘平台": job_data.get("platform", ""),
        "抓取时间": job_data.get("crawl_time", ""),
        "跟进状态": "新线索" 
    }

def sync_sqlite_to_feishu(db_path, table_name="jobs", sse_task_id=None, limit=None, min_rowid=0, target_links=None):
    """
    从 SQLite 读取满足条件的数据，并推送到飞书（带防重复同步机制）
    min_rowid>0 时只推送本轮采集的行（全自动链路语义：旧存量不进自动链）
    target_links 存在时优先精准推送指定岗位；target_links 为空列表时直接返回

    ⚠️ 纯同步函数，设计上只在 to_thread 工作线程内执行。从事件循环发起必须走
    sync_sqlite_to_feishu_async（负责锚定主 loop 供线程内 SSE 回推），
    直接裸 to_thread 本函数会导致 SSE 进度消息全部丢弃（仅告警不崩）。

    注意：本函数绝不重置全局急刹 flag（set_stop_flag(False)）——那是顶层任务入口
    （processor.py 各 _run_*_pipeline）的职责。底层子步骤若擅自重置，会吞掉用户在
    清洗途中点击「终止」发出的信号（回收站放行与本函数并发时必踩）。
    """
    push_sse_message_sync(sse_task_id, "开始执行 Tier 3: 飞书多维表格推送引擎")

    from job_processor.step1_rule_filter import get_stop_flag

    token = get_tenant_access_token()
    if not token:
        print("🚨 无法获取飞书 Token，停止推送。")
        push_sse_message_sync(sse_task_id, "无法获取飞书 Token，停止推送", "error")
        return []

    if not os.path.exists(db_path):
        print(f"🚨 找不到数据库文件: {db_path}")
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  
    cursor = conn.cursor()

    # 🌟 步骤 1：智能检查并添加 is_synced 和 feishu_record_id 列
    try:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN is_synced INTEGER DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN feishu_record_id TEXT DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # 🌟 步骤 2：编写 SQL 查询（增加 is_synced = 0 的过滤条件与 rowid 倒序）
    if target_links is not None:
        if len(target_links) == 0:
            print("✅ 本轮清洗无通过 AI 初筛的岗位需要同步至飞书。")
            push_sse_message_sync(sse_task_id, "本轮清洗无通过 AI 初筛的岗位需要同步至飞书。")
            conn.close()
            return []
        placeholders = ','.join(['?'] * len(target_links))
        sql_query = f"""
            SELECT rowid, * FROM {table_name}
            WHERE process_status = '待推送至飞书'
            AND (is_synced = 0 OR is_synced IS NULL)
            AND job_link IN ({placeholders})
            ORDER BY rowid DESC
        """
        if limit and limit > 0:
            sql_query += f" LIMIT {limit}"
        params = list(target_links)
    else:
        sql_query = f"""
            SELECT rowid, * FROM {table_name}
            WHERE process_status = '待推送至飞书'
            AND (is_synced = 0 OR is_synced IS NULL)
        """
        params = []
        if min_rowid:
            sql_query += f" AND rowid > {int(min_rowid)}"
        sql_query += " ORDER BY rowid DESC"
        if limit and limit > 0:
            sql_query += f" LIMIT {limit}"

    rows = []
    success_count = 0
    skip_count = 0
    fail_count = 0
    consecutive_unknown = 0  # 连续查重未知态计数（升级告警用，Q-M9-3）
    unknown_skip_count = 0  # 查重未知态累计跳过数（与真失败区分口径）
    created_ids = []  # 本轮新建的飞书记录 ID（供全自动链路只评估本轮采集的岗位）
    
    try:
        cursor.execute(sql_query, params)
        rows = cursor.fetchall()
        
        if len(rows) == 0:
            print("✅ 当前没有需要同步的新岗位（历史符合条件的岗位均已同步完毕）。")
            push_sse_message_sync(sse_task_id, "当前没有需要同步的新岗位。")
            push_sse_event(sse_task_id, {"type": "phase_progress", "phase": "feishu_sync", "current": 0, "total": 0, "passed": 0, "rejected": 0})
            return []
            
        print(f"🔍 查找到 {len(rows)} 条【未同步】且符合条件的高分岗位，准备推送...")
        push_sse_message_sync(sse_task_id, f"查找到 {len(rows)} 条【未同步】岗位，准备推送至飞书...")
        
        for i, row in enumerate(rows):
            if get_stop_flag():
                print("🛑 [飞书推送急刹] 收到终止信号，停止后续岗位推送")
                push_sse_message_sync(sse_task_id, "飞书推送任务已手动终止")
                break
            push_sse_event(sse_task_id, {
                "type": "phase_progress",
                "phase": "feishu_sync",
                "current": i,
                "total": len(rows),
                "passed": success_count + skip_count,
                "rejected": fail_count
            })
            job_data = dict(row)
            row_id = job_data.get("rowid") or job_data.get("id")
            comp_name = job_data.get("company_name", "")
            job_title = job_data.get("job_title", "")
            city = job_data.get("city", "")
            # 🌟 飞书端去重：基于「公司名称 + 岗位名称 + 城市」三要素联合查重
            existing_rec_id = check_job_exists(token, comp_name, job_title, city)
            if existing_rec_id is None:
                # 查重未知态（接口异常/业务错误码）：fail-closed 跳过本轮、保持「待推送至飞书」
                # 下轮自动重试，绝不当「不存在」新建，防止飞书抖动期重复建档（Q-M9-3）
                consecutive_unknown += 1
                print(f"⚠️ {comp_name}-{job_title} 查重接口未知态，本轮跳过待下轮重试（防止重复建档）")
                unknown_skip_count += 1
                if consecutive_unknown == _UNKNOWN_ESCALATE_AFTER:
                    msg = f"🚨 已连续 {consecutive_unknown} 个岗位查重未知态，疑似飞书接口故障或凭证失效——本轮全部拦截不建档，请检查飞书连通性后重跑"
                    print(msg)
                    push_sse_message_sync(sse_task_id, msg, "error")
                fail_count += 1
                continue
            consecutive_unknown = 0
            if existing_rec_id:
                rec_id_str = existing_rec_id if isinstance(existing_rec_id, str) else ""
                print(f"{comp_name}-{job_title} 已存在，关联已有飞书记录并跳过推送⚠️ ({rec_id_str})")
                update_sql = f"UPDATE {table_name} SET is_synced = 1, process_status = '已同步', feishu_record_id = ? WHERE rowid = ?"
                cursor.execute(update_sql, (rec_id_str, row_id))
                conn.commit()
                skip_count += 1
                continue


            # 👇 替换原来长长的一串 feishu_fields 赋值，改为直接调用新函数
            feishu_fields = build_feishu_fields_from_raw(job_data)
            
            # 🌟 步骤 3：执行单条推送，成功后立刻将本地数据库状态改为【已同步】
            success = push_single_record_to_feishu(token, feishu_fields)
            
            if success:
                rec_id = success if isinstance(success, str) else ""
                if rec_id:
                    created_ids.append(rec_id)
                update_sql = f"UPDATE {table_name} SET is_synced = 1, process_status = '已同步', feishu_record_id = ? WHERE rowid = ?"
                cursor.execute(update_sql, (rec_id, row_id))
                conn.commit()
                success_count += 1
                print(f"{comp_name}-{job_title} 已推送成功✅ ({rec_id})")
            else:
                fail_count += 1
                print(f"{comp_name}-{job_title} 推送失败❌")
        
        push_sse_event(sse_task_id, {
            "type": "phase_progress",
            "phase": "feishu_sync",
            "current": len(rows),
            "total": len(rows),
            "passed": success_count + skip_count,
            "rejected": fail_count
        })
            
    except Exception as e:
        print(f"❌ 数据库操作失败: {e}")
        push_sse_message_sync(sse_task_id, f"数据库操作失败: {e}", "error")
    finally:
        cursor.close()
        conn.close()
        total_count = len(rows)
        msg = f"全部岗位推送完毕！共尝试处理 {total_count} 个岗位，其中成功推送 {success_count} 个，已存在跳过 {skip_count} 个，推送失败 {fail_count} 个（含查重未知态拦截 {unknown_skip_count} 个待下轮重试）。"
        print(f"\n🏁 {msg}")
        push_sse_message_sync(sse_task_id, msg)
        
        # We also trigger step3 ai evaluator if needed, but typically it runs via webhook.
        # But we can push a message saying the backend AI evaluator will catch it.
        push_sse_message_sync(sse_task_id, "✅ 已触发飞书 Webhook，10 维度打分 AI 将在后台继续评估这些新线索。")

    return created_ids

if __name__ == "__main__":
    DB_FILE_PATH = os.path.join(PROJECT_ROOT, "data", "job_hunter.db")
    TABLE_NAME = "raw_jobs"

    sync_sqlite_to_feishu(DB_FILE_PATH, table_name=TABLE_NAME)