import asyncio
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

# 获取项目根目录
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(CURRENT_DIR)))
DB_PATH = os.path.join(PROJECT_ROOT, "data", "job_hunter.db")

@contextmanager
def get_db_connection(timeout: float = 30.0, row_factory=None):
    """安全上下文管理器：解决 Python 标准库 sqlite3.connect 上下文只管事务不关闭连接的缺陷，
    保证 100% 在 finally 中调用 conn.close()，杜绝句柄泄漏与锁库。
    """
    conn = sqlite3.connect(DB_PATH, timeout=timeout)
    if row_factory:
        conn.row_factory = row_factory
    try:
        yield conn
    finally:
        conn.close()

router = APIRouter()

class GlobalRunRequest(BaseModel):
    limit: int | None = 10

class SyncFeishuRequest(BaseModel):
    limit: int | None = 50

@router.get("/stats")
async def get_processor_stats():
    """获取清洗管道的待处理统计数据与各状态池流水量"""
    try:
        with get_db_connection(timeout=30.0) as conn:
            cursor = conn.cursor()

            # 1. 获取小红书待清洗数量
            try:
                cursor.execute('SELECT COUNT(*) FROM xhs_raw_posts WHERE clean_status = "PENDING"')
                xhs_pending = cursor.fetchone()[0]
            except sqlite3.OperationalError:
                xhs_pending = 0

            # 2. 获取全平台待清洗数量 (所有刚入库待处理的数据)
            try:
                cursor.execute("SELECT platform, COUNT(*) FROM raw_jobs WHERE process_status = '已存入数据' GROUP BY platform")
                rows = cursor.fetchall()
                raw_pending = sum(count for _, count in rows)
                global_breakdown = dict(rows)
            except sqlite3.OperationalError:
                raw_pending = 0
                global_breakdown = {}

            # 3. 待 AI 清洗数量 (已过硬规则初筛，等待大模型排雷)
            try:
                cursor.execute("SELECT COUNT(*) FROM raw_jobs WHERE process_status IN ('待AI初筛', '待AI清洗')")
                ai_pending = cursor.fetchone()[0]
            except sqlite3.OperationalError:
                ai_pending = 0

            # 4. 待推送至飞书数量 (已过AI清洗，排队同步中)
            try:
                cursor.execute("SELECT COUNT(*) FROM raw_jobs WHERE process_status = '待推送至飞书' AND (is_synced = 0 OR is_synced IS NULL)")
                ready_to_sync = cursor.fetchone()[0]
            except sqlite3.OperationalError:
                ready_to_sync = 0

            # 5. 已同步至飞书数量（优先读取飞书实时快照，确保与工作台岗位列表 1:1 精确对齐）
            try:
                from app.core.cache import JobCache
                feishu_jobs = JobCache.get() or JobCache.get_stale()
                if feishu_jobs is not None:
                    synced_count = len(feishu_jobs)
                else:
                    # 🌟 降级口径与飞书表对齐：「已同步」+「已进行打分」（打分是飞书 webhook 回写的后继状态）。
                    # 不能用 is_synced=1：放行后被再次淘汰的行 is_synced 仍为 1，会虚增数百条
                    cursor.execute("SELECT COUNT(*) FROM raw_jobs WHERE process_status IN ('已同步', '已进行打分')")
                    synced_count = cursor.fetchone()[0]
            except Exception:
                try:
                    cursor.execute("SELECT COUNT(*) FROM raw_jobs WHERE process_status IN ('已同步', '已进行打分')")
                    synced_count = cursor.fetchone()[0]
                except sqlite3.OperationalError:
                    synced_count = 0

            # 6. 清洗淘汰数量 (细分：规则拦截 vs AI排雷淘汰)
            try:
                cursor.execute("SELECT process_status, COUNT(*) FROM raw_jobs WHERE process_status IN ('清洗淘汰', 'ai清洗淘汰') GROUP BY process_status")
                rej_map = dict(cursor.fetchall())
                rejected_rule_count = rej_map.get('清洗淘汰', 0)
                rejected_ai_count = rej_map.get('ai清洗淘汰', 0)
                rejected_count = rejected_rule_count + rejected_ai_count
            except sqlite3.OperationalError:
                rejected_count = 0
                rejected_rule_count = 0
                rejected_ai_count = 0

        return {
            "xhs_pending": xhs_pending,
            "raw_pending": raw_pending,
            "ai_pending": ai_pending,
            "global_pending": raw_pending,  # 保持旧字段兼容
            "global_breakdown": global_breakdown,
            "ready_to_sync": ready_to_sync,
            "synced_count": synced_count,
            "rejected_count": rejected_count,
            "rejected_rule_count": rejected_rule_count,
            "rejected_ai_count": rejected_ai_count,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

_global_clean_lock = asyncio.Lock()
_xhs_clean_lock = asyncio.Lock()

@router.post("/run-xhs")
async def run_xhs_cleaner(background_tasks: BackgroundTasks):
    """触发小红书多模态清洗任务（加锁防重）"""
    from job_processor import xhs_vision_cleaner
    # 🌟 统一互斥锁：与爬虫抓完自动触发的清洗共用同一把模块级锁，
    # 任一入口在跑时另一入口拿不到锁，杜绝双 cleaner 自愈回收互踩重复烧 Token
    if xhs_vision_cleaner.XHS_CLEAN_LOCK.locked() or _xhs_clean_lock.locked():
        raise HTTPException(status_code=409, detail="小红书多模态清洗正在后台执行中，请勿重复触发！")

    task_id = f"clean_xhs_{uuid.uuid4().hex[:8]}"

    from app.tasks.state import task_queues
    task_queues[task_id] = asyncio.Queue()

    background_tasks.add_task(_run_xhs_vision_cleaner, task_id)
    return {"status": "success", "task_id": task_id}

@router.post("/run-global")
async def run_global_cleaner(request: GlobalRunRequest, background_tasks: BackgroundTasks):
    """触发全平台漏斗式三层清洗管道（加锁防重）"""
    from job_processor.step1_rule_filter import GLOBAL_CLEAN_LOCK
    if _global_clean_lock.locked() or GLOBAL_CLEAN_LOCK.locked():
        raise HTTPException(status_code=409, detail="清洗或推送任务正在后台执行中，请勿重复触发！")

    task_id = f"clean_global_{uuid.uuid4().hex[:8]}"
    from app.tasks.state import task_queues
    task_queues[task_id] = asyncio.Queue()
    background_tasks.add_task(_run_global_pipeline, task_id, request.limit)
    return {"status": "success", "task_id": task_id}

@router.post("/run-hard-filter")
async def run_hard_filter_cleaner(request: GlobalRunRequest, background_tasks: BackgroundTasks):
    """阶段一独立触发：纯硬规则初筛（0 Token，本地毫秒级过滤）"""
    from job_processor.step1_rule_filter import GLOBAL_CLEAN_LOCK
    if _global_clean_lock.locked() or GLOBAL_CLEAN_LOCK.locked():
        raise HTTPException(status_code=409, detail="清洗或推送任务正在后台执行中，请勿重复触发！")

    task_id = f"clean_hard_{uuid.uuid4().hex[:8]}"
    from app.tasks.state import task_queues
    task_queues[task_id] = asyncio.Queue()
    background_tasks.add_task(_run_hard_filter_pipeline, task_id, request.limit)
    return {"status": "success", "task_id": task_id}

@router.post("/run-ai-scout")
async def run_ai_scout_cleaner(request: GlobalRunRequest, background_tasks: BackgroundTasks):
    """阶段二独立触发：AI 大模型深度排雷（消耗 Token，对待AI清洗池执行）"""
    from job_processor.step1_rule_filter import GLOBAL_CLEAN_LOCK
    if _global_clean_lock.locked() or GLOBAL_CLEAN_LOCK.locked():
        raise HTTPException(status_code=409, detail="清洗或推送任务正在后台执行中，请勿重复触发！")

    task_id = f"clean_ai_{uuid.uuid4().hex[:8]}"
    from app.tasks.state import task_queues
    task_queues[task_id] = asyncio.Queue()
    background_tasks.add_task(_run_ai_scout_pipeline, task_id, request.limit)
    return {"status": "success", "task_id": task_id}

@router.post("/skip-ai-sync")
async def skip_ai_sync_cleaner(request: GlobalRunRequest, background_tasks: BackgroundTasks):
    """免 AI 排雷直通飞书：跳过大模型，硬规则合格后直接入库飞书"""
    from job_processor.step1_rule_filter import GLOBAL_CLEAN_LOCK
    if _global_clean_lock.locked() or GLOBAL_CLEAN_LOCK.locked():
        raise HTTPException(status_code=409, detail="清洗或推送任务正在后台执行中，请勿重复触发！")

    task_id = f"skip_ai_{uuid.uuid4().hex[:8]}"
    from app.tasks.state import task_queues
    task_queues[task_id] = asyncio.Queue()
    background_tasks.add_task(_run_skip_ai_sync_pipeline, task_id, request.limit)
    return {"status": "success", "task_id": task_id}

@router.post("/sync-feishu")
async def sync_feishu_standalone(request: SyncFeishuRequest, background_tasks: BackgroundTasks):
    """独立触发存量待推送岗位同步至飞书（加锁防重）"""
    from job_processor.step1_rule_filter import GLOBAL_CLEAN_LOCK
    if _global_clean_lock.locked() or GLOBAL_CLEAN_LOCK.locked():
        raise HTTPException(status_code=409, detail="清洗或推送任务正在后台执行中，请勿重复触发！")

    task_id = f"sync_feishu_{uuid.uuid4().hex[:8]}"
    from app.tasks.state import task_queues
    task_queues[task_id] = asyncio.Queue()

    background_tasks.add_task(_run_sync_feishu_pipeline, task_id, request.limit)
    return {"status": "success", "task_id": task_id}


class UnrejectRequest(BaseModel):
    job_link: str | None = None
    job_id: str | None = None
    pipeline_task_id: str | None = None

@router.get("/trash-bin")
async def get_trash_bin():
    """获取清洗淘汰的岗位列表（回收站）"""
    try:
        with get_db_connection(timeout=30.0, row_factory=sqlite3.Row) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT rowid, job_link, platform, job_title, company_name, city, salary,
                       process_status, reject_reason, jd_text
                FROM raw_jobs
                WHERE process_status IN ('清洗淘汰', 'ai清洗淘汰')
                ORDER BY rowid DESC
                LIMIT 200
            ''')
            rows = cursor.fetchall()
            jobs = [dict(row) for row in rows]
        return {"status": "success", "data": jobs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/unreject")
async def unreject_job(request: UnrejectRequest, background_tasks: BackgroundTasks):
    """放行被误杀的岗位，并自动接入 LangGraph 评估流转流水线"""
    try:
        row = None
        row_id = None
        with get_db_connection(timeout=30.0, row_factory=sqlite3.Row) as conn:
            cursor = conn.cursor()

            # 1. 优先按 rowid / job_id 精确定位
            if request.job_id:
                try:
                    row_id_val = int(str(request.job_id).replace("raw_", ""))
                    cursor.execute("SELECT rowid, * FROM raw_jobs WHERE rowid = ?", (row_id_val,))
                    row = cursor.fetchone()
                except Exception:
                    row = None

            # 2. 降级按 job_link 定位
            if not row and request.job_link:
                clean_link = request.job_link.strip()
                cursor.execute("SELECT rowid, * FROM raw_jobs WHERE job_link = ? OR job_link LIKE ?", (clean_link, f"{clean_link.split('?')[0]}%"))
                row = cursor.fetchone()

            if row:
                row_id = row["rowid"]
                cursor.execute('''
                    UPDATE raw_jobs
                    SET process_status = '待推送至飞书', reject_reason = NULL
                    WHERE rowid = ?
                ''', (row_id,))
                conn.commit()
                print(f"🔓 [Processor] SQLite 已放行岗位 rowid={row_id}, 【{row['company_name']} - {row['job_title']}】", flush=True)
            elif request.job_link:
                cursor.execute('''
                    UPDATE raw_jobs
                    SET process_status = '待推送至飞书', reject_reason = NULL
                    WHERE job_link = ?
                ''', (request.job_link.strip(),))
                conn.commit()
                print(f"🔓 [Processor] SQLite 依据链接放行岗位: {request.job_link}", flush=True)
            else:
                raise HTTPException(status_code=400, detail="未提供有效的 job_id 或 job_link")

        task_id = request.pipeline_task_id or f"unreject_{uuid.uuid4().hex[:8]}"
        background_tasks.add_task(_run_unreject_and_evaluate, task_id, row_id, request.job_link)

        return {"status": "success", "message": "已放行并开始 AI 评估流转", "task_id": task_id}
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [Processor] unreject_job 异常: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/trash-bin-count")
async def get_trash_bin_count():
    """获取回收站待复核的数量"""
    try:
        with get_db_connection(timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM raw_jobs WHERE process_status IN ('清洗淘汰', 'ai清洗淘汰')")
            count = cursor.fetchone()[0]
        return {"status": "success", "count": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/confirm-reject")
async def confirm_reject(request: UnrejectRequest):
    """确认岗位被正确淘汰，从回收站彻底归档"""
    try:
        with get_db_connection(timeout=30.0) as conn:
            cursor = conn.cursor()

            if request.job_id:
                try:
                    row_id_val = int(str(request.job_id).replace("raw_", ""))
                    cursor.execute("UPDATE raw_jobs SET process_status = '已确认淘汰' WHERE rowid = ?", (row_id_val,))
                except Exception:
                    pass

            if request.job_link:
                cursor.execute("UPDATE raw_jobs SET process_status = '已确认淘汰' WHERE job_link = ?", (request.job_link.strip(),))

            conn.commit()

        return {"status": "success", "message": "已确认淘汰"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/empty-trash")
async def empty_trash():
    """一键清空整个回收站"""
    try:
        with get_db_connection(timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE raw_jobs
                SET process_status = '已确认淘汰'
                WHERE process_status IN ('清洗淘汰', 'ai清洗淘汰')
            ''')
            deleted_count = cursor.rowcount
            conn.commit()

        return {"status": "success", "message": f"成功清空了 {deleted_count} 个岗位"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def _run_unreject_and_evaluate(task_id: str, row_id: int | None = None, job_link: str | None = None):
    """后台任务：同步飞书并无缝触发 LangGraph AI 评估流水线"""
    try:
        print(f"🚀 [白盒日志] 开始同步并评估被放行岗位: rowid={row_id}, link={job_link}, task_id={task_id}", flush=True)
        from app.automation.full_auto import run_single_job_pipeline_async
        from job_processor import step2_sync_feishu

        # 1. 提取被放行岗位的准确 job_link 并定向精准推送飞书（limit=1, target_links=[target_link]）
        target_link = job_link
        if not target_link and row_id:
            with get_db_connection(timeout=30.0, row_factory=sqlite3.Row) as conn:
                r = conn.execute("SELECT job_link FROM raw_jobs WHERE rowid = ?", (row_id,)).fetchone()
                if r and r["job_link"]:
                    target_link = r["job_link"]

        target_links = [target_link] if target_link else None
        # 🌟 推送临界区加锁：与清洗流水线/独立推送互斥，防止并发 check_job_exists
        # 竞态窗口内两边都查到「不存在」导致同一岗位在飞书双写。
        # 只锁定向推送这一小段；后续 AI 评估可能分钟级，不持锁，避免放行一个岗位锁死整个清洗面板。
        async with _global_clean_lock:
            # 锁内不可重置急刹 flag（否则会吞掉正在运行任务的终止信号）；同步推送期间尊重终止信号由 step2 内部 get_stop_flag 判定
            synced_ids = await asyncio.to_thread(step2_sync_feishu.sync_sqlite_to_feishu, DB_PATH, "raw_jobs", task_id, 1, target_links=target_links)

        # 2. 精确获取该岗位的 feishu_record_id
        record_id = None
        with get_db_connection(timeout=30.0, row_factory=sqlite3.Row) as conn:
            if row_id:
                r = conn.execute("SELECT feishu_record_id FROM raw_jobs WHERE rowid = ?", (row_id,)).fetchone()
            elif target_link:
                r = conn.execute("SELECT feishu_record_id FROM raw_jobs WHERE (job_link = ? OR job_link LIKE ?) AND feishu_record_id IS NOT NULL AND feishu_record_id != ''", (target_link, f"{target_link.split('?')[0]}%")).fetchone()
            else:
                r = None
            if r and r["feishu_record_id"]:
                record_id = r["feishu_record_id"]

        if not record_id and synced_ids and isinstance(synced_ids, list) and len(synced_ids) > 0:
            record_id = synced_ids[0]

        if record_id:
            print(f"✅ [白盒日志] 飞书同步就绪 (record_id={record_id})，立即触发 AI 初评及流水线...", flush=True)
            await run_single_job_pipeline_async(record_id=record_id, raw_rowid=str(row_id) if row_id else None, pipeline_task_id=task_id)
        else:
            print(f"⚠️ [白盒日志] 未能获取到放行岗位的飞书 record_id (rowid={row_id})，请检查飞书网络或同步配置", flush=True)

    except Exception as e:
        print(f"❌ [白盒日志] 误杀放行及评估流转失败: {str(e)}", flush=True)

async def _run_xhs_vision_cleaner(task_id: str):
    # 🌟 双重防线：路由入口已查锁（409 拒绝），后台体再由 run_vision_cleaner
    # 内部的模块级统一锁兜底。wait_if_busy=True 为排队语义：极端情况下爬虫
    # 自动清洗刚启动抢到锁，手动触发会排队等它结束再执行，绝不静默丢弃任务。
    async with _xhs_clean_lock:
        try:
            from job_processor import xhs_vision_cleaner

            print(f"🚀 [Processor] 开始小红书多模态清洗, 任务ID: {task_id}")
            result = await xhs_vision_cleaner.run_vision_cleaner(sse_task_id=task_id, wait_if_busy=True)
            if result == "skipped":
                # 仅在无 wait_if_busy 路径下出现，此处兜底记录（正常不应触达）
                print(f"⚠️ [Processor] 小红书清洗被跳过: {task_id}, result={result}")
            else:
                print(f"✅ [Processor] 小红书多模态清洗完成, 任务ID: {task_id} (result={result})")
        except Exception as e:
            print(f"❌ 小红书多模态清洗任务崩溃: {str(e)}")
            from app.tasks.state import task_queues
            if task_id in task_queues:
                err_data = json.dumps({"type": "error", "message": f"小红书清洗崩溃: {str(e)}"}, ensure_ascii=False)
                await task_queues[task_id].put(f"data: {err_data}\n\n")
        finally:
            from app.tasks.state import schedule_task_cleanup, task_queues
            if task_id in task_queues:
                await task_queues[task_id].put('data: {"type": "end"}\n\n')
            schedule_task_cleanup(task_id, delay_seconds=300)

async def _run_global_pipeline(task_id: str, limit: int):
    async with _global_clean_lock:
        try:
            from job_processor import step1_rule_filter, step2_sync_feishu

            # 🌟 急刹 flag 只允许在顶层任务入口重置（step2 内部已禁止重置，
            # 否则会吞掉用户在清洗/推送途中点击终止发出的信号）
            step1_rule_filter.set_stop_flag(False)

            print(f"🚀 [Processor] 开始全平台漏斗式清洗, 任务ID: {task_id}, limit: {limit}")

            # Step 1: 硬规则拦截 & AI 侦察兵初筛（返回本轮真正进入「待推送至飞书」的岗位列表）
            passed_links = await step1_rule_filter._async_run_pipeline(sse_task_id=task_id, limit=limit)

            # Step 2: 同步飞书 (优先精准推送本轮刚刚通过 AI 初筛的岗位)
            # 🌟 用户点击「终止」后立即跳过推送：前端已展示「已终止」，若后台仍静默写飞书会产生误解
            from app.tasks.state import task_queues
            if step1_rule_filter.get_stop_flag():
                print(f"🛑 [Processor] 检测到终止信号，跳过 Step 2 飞书推送, 任务ID: {task_id}")
                push_msg = {"type": "log", "message": "🔗 [飞书同步] 已终止：本轮通过 AI 初筛的岗位保留在待推送池，未推送至飞书"}
                if task_id in task_queues:
                    await task_queues[task_id].put(f"data: {json.dumps(push_msg, ensure_ascii=False)}\n\n")
            else:
                await asyncio.to_thread(step2_sync_feishu.sync_sqlite_to_feishu, DB_PATH, "raw_jobs", task_id, limit, target_links=passed_links)

            print(f"✅ [Processor] 全平台漏斗式清洗完成, 任务ID: {task_id}")
        except Exception as e:
            print(f"❌ 全局清洗管道任务崩溃: {str(e)}")
            from app.tasks.state import task_queues
            if task_id in task_queues:
                err_data = json.dumps({"type": "error", "message": f"全局清洗管道崩溃: {str(e)}"}, ensure_ascii=False)
                await task_queues[task_id].put(f"data: {err_data}\n\n")
        finally:
            from app.tasks.state import schedule_task_cleanup, task_queues
            if task_id in task_queues:
                await task_queues[task_id].put('data: {"type": "end"}\n\n')
            schedule_task_cleanup(task_id, delay_seconds=300)

async def _run_sync_feishu_pipeline(task_id: str, limit: int):
    async with _global_clean_lock:
        try:
            from job_processor import step1_rule_filter, step2_sync_feishu
            # 🌟 急刹 flag 顶层入口重置（step2 内部已禁止重置，此处为独立推送任务的唯一重置点）
            step1_rule_filter.set_stop_flag(False)
            print(f"🚀 [Processor] 开始执行存量岗位飞书独立推送, 任务ID: {task_id}, limit: {limit}")
            await asyncio.to_thread(step2_sync_feishu.sync_sqlite_to_feishu, DB_PATH, "raw_jobs", task_id, limit)
            print(f"✅ [Processor] 存量岗位飞书推送完成, 任务ID: {task_id}")
        except Exception as e:
            print(f"❌ 飞书推送任务崩溃: {str(e)}")
            from app.tasks.state import task_queues
            if task_id in task_queues:
                err_data = json.dumps({"type": "error", "message": f"飞书推送任务崩溃: {str(e)}"}, ensure_ascii=False)
                await task_queues[task_id].put(f"data: {err_data}\n\n")
        finally:
            from app.tasks.state import schedule_task_cleanup, task_queues
            if task_id in task_queues:
                await task_queues[task_id].put('data: {"type": "end"}\n\n')
            schedule_task_cleanup(task_id, delay_seconds=300)

async def _run_hard_filter_pipeline(task_id: str, limit: int):
    async with _global_clean_lock:
        try:
            from job_processor import step1_rule_filter
            print(f"🚀 [Processor] 开始单跑硬规则初筛 (Tier 1), 任务ID: {task_id}, limit: {limit}")
            res = await step1_rule_filter._async_run_hard_filter_only(sse_task_id=task_id, limit=limit)
            print(f"✅ [Processor] 单跑硬规则初筛完成: {res}, 任务ID: {task_id}")
        except Exception as e:
            print(f"❌ 硬规则初筛任务崩溃: {str(e)}")
            from app.tasks.state import task_queues
            if task_id in task_queues:
                err_data = json.dumps({"type": "error", "message": f"硬规则初筛崩溃: {str(e)}"}, ensure_ascii=False)
                await task_queues[task_id].put(f"data: {err_data}\n\n")
        finally:
            from app.tasks.state import schedule_task_cleanup, task_queues
            if task_id in task_queues:
                await task_queues[task_id].put('data: {"type": "end"}\n\n')
            schedule_task_cleanup(task_id, delay_seconds=300)

async def _run_ai_scout_pipeline(task_id: str, limit: int):
    async with _global_clean_lock:
        try:
            from job_processor import step1_rule_filter
            print(f"🚀 [Processor] 开始单跑 AI 深度排雷 (Tier 2), 任务ID: {task_id}, limit: {limit}")
            passed_links = await step1_rule_filter._async_run_ai_scout_only(sse_task_id=task_id, limit=limit)
            print(f"✅ [Processor] AI 深度排雷完成, 最终通过 {len(passed_links)} 条, 任务ID: {task_id}")
        except Exception as e:
            print(f"❌ AI 深度排雷任务崩溃: {str(e)}")
            from app.tasks.state import task_queues
            if task_id in task_queues:
                err_data = json.dumps({"type": "error", "message": f"AI排雷任务崩溃: {str(e)}"}, ensure_ascii=False)
                await task_queues[task_id].put(f"data: {err_data}\n\n")
        finally:
            from app.tasks.state import schedule_task_cleanup, task_queues
            if task_id in task_queues:
                await task_queues[task_id].put('data: {"type": "end"}\n\n')
            schedule_task_cleanup(task_id, delay_seconds=300)

async def _run_skip_ai_sync_pipeline(task_id: str, limit: int):
    async with _global_clean_lock:
        try:
            from job_processor import step1_rule_filter, step2_sync_feishu
            # 🌟 急刹 flag 顶层入口重置（step2 内部已禁止重置）
            step1_rule_filter.set_stop_flag(False)
            print(f"🚀 [Processor] 开始免 AI 直推飞书, 任务ID: {task_id}, limit: {limit}")
            promoted_links = await step1_rule_filter._async_skip_ai_to_feishu(sse_task_id=task_id, limit=limit)
            if promoted_links:
                await asyncio.to_thread(step2_sync_feishu.sync_sqlite_to_feishu, DB_PATH, "raw_jobs", task_id, limit, target_links=promoted_links)
            print(f"✅ [Processor] 免 AI 直推飞书完成, 任务ID: {task_id}")
        except Exception as e:
            print(f"❌ 免 AI 直推飞书崩溃: {str(e)}")
            from app.tasks.state import task_queues
            if task_id in task_queues:
                err_data = json.dumps({"type": "error", "message": f"免AI直推飞书崩溃: {str(e)}"}, ensure_ascii=False)
                await task_queues[task_id].put(f"data: {err_data}\n\n")
        finally:
            from app.tasks.state import schedule_task_cleanup, task_queues
            if task_id in task_queues:
                await task_queues[task_id].put('data: {"type": "end"}\n\n')
            schedule_task_cleanup(task_id, delay_seconds=300)
