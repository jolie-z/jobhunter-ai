import os
import json
import sqlite3
import asyncio
from datetime import datetime
from openai import AsyncOpenAI

# 获取项目根目录
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
DB_PATH = os.path.join(PROJECT_ROOT, "data", "job_hunter.db")

# 🌟 全局急刹车开关：支持手动终止小红书多模态清洗
GLOBAL_STOP_FLAG = False

# 🌟 小红书清洗统一互斥锁（模块级，全系统唯一实例）：
# 爬虫抓完自动触发的清洗与数据探测面板手动触发的清洗共用此锁，
# 防止双 cleaner 并发 → 自愈回收互踩 → 同一批笔记重复过视觉大模型烧双倍 Token。
XHS_CLEAN_LOCK = asyncio.Lock()

def set_stop_flag(value: bool):
    global GLOBAL_STOP_FLAG
    GLOBAL_STOP_FLAG = bool(value)
    print(f"🛑 [XhsVisionCleaner] GLOBAL_STOP_FLAG -> {GLOBAL_STOP_FLAG}")

def get_stop_flag() -> bool:
    return GLOBAL_STOP_FLAG

# 引入配置
import sys
sys.path.insert(0, PROJECT_ROOT)
from app.core.config import settings
from common.config import _cfg
# 🌟 统一 Token 埋点
from app.core.llm_tracker import make_tracked_client

def _using_dedicated_vision_channel() -> bool:
    """配置了 CLEANER_VISION_MODEL 即启用清洗专属视觉通道。"""
    return bool((_cfg("CLEANER_VISION_MODEL", json_key="CLEANER_VISION_MODEL") or "").strip())

def _vision_model() -> str:
    """视觉模型名动态读取（settings.json > .env），配置页保存即生效。
    优先 CLEANER_VISION_MODEL（小红书清洗专属），未配置则降级主通道 VISION_MODEL。"""
    dedicated = (_cfg("CLEANER_VISION_MODEL", json_key="CLEANER_VISION_MODEL") or "").strip()
    if dedicated:
        return dedicated
    return _cfg("VISION_MODEL", json_key="VISION_MODEL") or "mimo-v2.5"

_client = None
_client_sig = None

def _get_client():
    """惰性构建并缓存视觉清洗客户端；Key/URL/模型变更时自动重建（配置页保存即生效）。

    路由：CLEANER_VISION_MODEL 已配置 → 清洗专属凭证（CLEANER_LLM_*，缺省回落主通道凭证）；
    未配置 → 主通道（OPENAI_*）+ VISION_MODEL。
    """
    global _client, _client_sig
    key = url = ""
    if _using_dedicated_vision_channel():
        key = _cfg("CLEANER_LLM_API_KEY", json_key="CLEANER_LLM_API_KEY")
        url = _cfg("CLEANER_LLM_BASE_URL", json_key="CLEANER_LLM_BASE_URL")
    if not key or not url:
        key = _cfg("OPENAI_API_KEY", "LLM_API_KEY", "api_key", json_key="OPENAI_API_KEY")
        url = _cfg("OPENAI_BASE_URL", "LLM_BASE_URL", "base_url", json_key="OPENAI_BASE_URL")
    model = _vision_model()
    sig = (key, url, model)
    if _client is None or _client_sig != sig:
        # 🌟 经包装后自动埋点 token 消耗
        _client = make_tracked_client(AsyncOpenAI(api_key=key, base_url=url), model_default=model, caller="xhs_vision_cleaner")
        _client_sig = sig
    return _client

async def push_sse_message(task_id: str, message: str, status="info"):
    if not task_id: return
    try:
        from app.tasks.state import task_queues
        if task_id in task_queues:
            data = {"type": "log", "message": f"🤖 [AI清洗] {message}"}
            if status == "error":
                data["type"] = "error"
            msg = f'data: {json.dumps(data, ensure_ascii=False)}\n\n'
            await task_queues[task_id].put(msg)
    except Exception:
        pass

async def push_sse_progress(task_id: str, current: int, total: int):
    if not task_id: return
    try:
        from app.tasks.state import task_queues
        if task_id in task_queues:
            data = {
                "type": "progress",
                "platform": "xiaohongshu",
                "total_inserted": current,
                "target_jobs": total,
                "current_page": 1,
                "timestamp": datetime.now().isoformat()
            }
            msg = f'data: {json.dumps(data, ensure_ascii=False)}\n\n'
            await task_queues[task_id].put(msg)
    except Exception:
        pass

PROMPT_TEMPLATE = """
你是小红书上的一个资深猎头分析师。这是一篇小红书笔记的配图（图片URL列表）和粗略提取的文字信息。
请判断这是否是一个真实的【招聘贴】或者【求职贴/内推贴】包含具体的岗位信息。

如果不是真实的招聘相关帖子（比如只是单纯的生活分享、知识科普等），请严格输出且只输出一个词汇: NOT_A_JOB。

如果是招聘相关的帖子，请注意：一篇笔记中通常会包含【多个】岗位（可能在不同图片里，也可能在同一张图片里）。请你把所有找到的岗位都提取出来，并以 JSON 数组（Array）的格式返回。
你必须严格输出如下 JSON 数组格式（不要包含 markdown 代码块符号如 ```json）：

[
    {
        "job_title": "提取的岗位名称，如果没有请根据职责概括",
        "company_name": "提取的公司名称，如果未提及请输出 '未提及'",
        "salary": "薪资范围，如 15-20K，如果未提及请输出 '面议'",
        "city": "工作城市，如果未提及请输出 '全国/远程'",
        "jd_text": "工作职责、任职要求和加分项等（请原封不动地保留原始文本描述，如果有图片，请原模原样识别并提取图片中的职位描述文本，绝对不要进行任何总结、缩写或改写，请保持原样提取输出！）",
        "welfare_tags": "福利待遇标签，逗号分隔，如：双休,五险一金",
        "education_req": "学历要求，如：本科/大专/不限",
        "experience_req": "经验要求，如：3-5年/不限"
    }
]

请注意：尽可能从提供的所有图片里用你的 Vision 能力提取每一个岗位的文字。如果有多个岗位，请在 JSON 数组中输出多个对象。
原始文本内容如下：
%s
"""

async def process_single_post(record, sse_task_id=None):
    post_link, account_name, raw_text, image_urls_str = record
    
    print(f"🔄 [清洗] 正在分析笔记: {account_name}")
    print(f"      🔗 链接: {post_link}")
    await push_sse_message(sse_task_id, f"正在分析笔记: {account_name}")
    
    try:
        image_urls = json.loads(image_urls_str) if image_urls_str else []
    except:
        image_urls = []
        
    content_list = [
        {"type": "text", "text": PROMPT_TEMPLATE % raw_text}
    ]
    
    # 限制最多读取 9 张图（小红书多岗位一般在轮播图中），避免 token 爆炸
    for img_url in image_urls[:9]:
        content_list.append({
            "type": "image_url",
            "image_url": {
                "url": img_url
            }
        })
        
    messages = [{"role": "user", "content": content_list}]
    
    print(f"      👁️ 提取了 {len(image_urls[:9])} 张关键图片传入视觉模型...")
    await push_sse_message(sse_task_id, f"已提取 {len(image_urls[:9])} 张关键图片传入视觉模型...")
    
    print(f"      ⏳ 正在请求大模型 ({_vision_model()})，由于包含图片分析，通常需要 20-60 秒，请耐心等待...")
    await push_sse_message(sse_task_id, "正在进行图像多模态推理计算，可能需要 20-60 秒，请耐心等待...")
    import time
    start_time = time.time()
    
    try:
        response = await _get_client().chat.completions.create(
            model=_vision_model(),
            messages=messages,
            temperature=0.3,
            max_tokens=10000
        )
        
        elapsed = time.time() - start_time
        print(f"      ✅ 大模型返回成功！(耗时: {elapsed:.2f}秒)")
        
        result_text = response.choices[0].message.content.strip()
        print(f"      💬 模型原始返回片段: {result_text[:50]}...")
        
        if "NOT_A_JOB" in result_text:
            return "NOT_A_JOB", None
            
        # 尝试解析 JSON
        try:
            # 清理可能的 markdown 符号
            json_str = result_text.replace("```json", "").replace("```", "").strip()
            job_data_list = json.loads(json_str, strict=False)
            
            # 兼容大模型只返回了一个字典的情况
            if isinstance(job_data_list, dict):
                job_data_list = [job_data_list]
                
            print(f"      ✅ JSON解析成功: 共提取 {len(job_data_list)} 个岗位")
            return "SUCCESS", job_data_list
        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析失败，模型返回内容: {result_text}\n错误详情: {e}")
            await push_sse_message(sse_task_id, "解析失败，模型未返回标准 JSON", "error")
            return "FAILED", None
            
    except Exception as e:
        print(f"❌ LLM 请求异常: {str(e)}")
        await push_sse_message(sse_task_id, f"LLM 请求异常: {str(e)}", "error")
        return "FAILED", None

def insert_to_raw_jobs(job_data, post_link, publish_date=""):
    try:
        with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO raw_jobs 
                (job_link, job_title, company_name, city, jd_text, salary, welfare_tags, education_req, experience_req, platform, publish_date, crawl_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                post_link,
                job_data.get("job_title", ""),
                job_data.get("company_name", ""),
                job_data.get("city", ""),
                job_data.get("jd_text", ""),
                job_data.get("salary", ""),
                job_data.get("welfare_tags", ""),
                job_data.get("education_req", ""),
                job_data.get("experience_req", ""),
                "小红书",
                publish_date,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ))
            conn.commit()
    except Exception as e:
        print(f"❌ 写入 raw_jobs 失败: {str(e)}")

def update_xhs_status(post_link, status):
    try:
        with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE xhs_raw_posts SET clean_status = ? WHERE post_link = ?', (status, post_link))
            conn.commit()
    except Exception as e:
        print(f"❌ 更新状态失败: {str(e)}")

async def run_vision_cleaner(sse_task_id: str = None, wait_if_busy: bool = False):
    """小红书多模态清洗主入口（锁管理唯一收口处，调用方一律裸调用，禁止外部再包锁）。

    XHS_CLEAN_LOCK 是非可重入锁，若调用方外层持锁后再调本函数，内部 locked()
    恒为 True → 永远 skipped（曾因此废掉爬虫自动清洗管道，勿再犯）。

    - wait_if_busy=False：锁被其它 cleaner 占用时直接返回 skipped 不排队
      （防止同一触发源并发重复烧 Token）；
    - wait_if_busy=True：排队等锁（如爬虫抓完必须清洗已抓数据的场景，
      即使手动清洗在跑也等它结束后接续，绝不丢弃已抓数据）。

    自愈回收语义：能拿到锁 = 全系统没有其它 cleaner 在跑，此时把 PROCESSING
    回滚为 PENDING 是安全的（都是上次硬崩溃的僵尸行）；拿不到锁绝不回收。
    """
    if XHS_CLEAN_LOCK.locked() and not wait_if_busy:
        print("⚠️ [XHS清洗] 已有清洗任务在执行，跳过本次触发（防止重复烧 Token）")
        return "skipped"

    async with XHS_CLEAN_LOCK:
        if wait_if_busy and sse_task_id:
            await push_sse_message(sse_task_id, "已有清洗任务在执行，排队等待中...")
        set_stop_flag(False)
        print(f"🚀 [清洗启动] 小红书视觉大模型清洗管道 (模型: {_vision_model()})")
    
        # 发送状态切换通知给前端，将其从 running 切换为 cleaning
        if sse_task_id:
            try:
                from app.tasks.state import task_queues
                if sse_task_id in task_queues:
                    msg = f'data: {{"type": "phase_change", "phase": "cleaning"}}\n\n'
                    await task_queues[sse_task_id].put(msg)
            except Exception:
                pass
            
        await push_sse_message(sse_task_id, f"启动大模型清洗管道 (模型: {_vision_model()})")
    
        records = []
        try:
            with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
                cursor = conn.cursor()
            
                # 🌟 僵尸状态自愈回收（Self-Healing Reclamation）：
                # 若上次清洗中途硬崩溃或遇到重启，将残留卡在 PROCESSING 的笔记安全回滚为 PENDING
                cursor.execute("UPDATE xhs_raw_posts SET clean_status = 'PENDING' WHERE clean_status = 'PROCESSING'")
                reclaimed_xhs = cursor.rowcount
                if reclaimed_xhs > 0:
                    conn.commit()
                    print(f"🔄 [XHS清洗自愈] 成功回收 {reclaimed_xhs} 条因上次异常中断残留的 PROCESSING 笔记！")

                cursor.execute('SELECT post_link, account_name, raw_text, image_urls, publish_date FROM xhs_raw_posts WHERE clean_status = "PENDING" LIMIT 20')
                records = cursor.fetchall()
            
                if records:
                    # 🌟 原子行认领 (Atomic Claiming)：立即将这批笔记状态标记为 PROCESSING
                    # 防止并发的清洗任务重复抓取相同笔记调用大模型，造成 Token 重复消耗
                    claimed_links = [r[0] for r in records]
                    placeholders = ','.join(['?'] * len(claimed_links))
                    cursor.execute(f"UPDATE xhs_raw_posts SET clean_status = 'PROCESSING' WHERE post_link IN ({placeholders})", claimed_links)
                    conn.commit()
        except Exception as e:
            print(f"❌ 认领小红书待清洗笔记失败: {str(e)}")
            await push_sse_message(sse_task_id, f"读取数据库失败: {str(e)}", "error")
            return
    
        if not records:
            print("✅ [清洗结束] 暂无 PENDING 的原始数据需要清洗。")
            await push_sse_message(sse_task_id, "暂无待清洗数据，任务完成。")
            return
        
        print(f"📦 成功原子认领 {len(records)} 条待清洗数据，开始逐条处理...")
        await push_sse_message(sse_task_id, f"成功认领 {len(records)} 条待清洗笔记，开始结构化提取...")
    
        # 初始化前端的进度条显示 0/N
        await push_sse_progress(sse_task_id, 0, len(records))
    
        for i, record in enumerate(records):
            # 🌟 逐条循环前检查急刹车标志
            if get_stop_flag():
                print("🛑 [小红书清洗急刹] 收到手动终止信号，提前结束视觉清洗循环！")
                await push_sse_message(sse_task_id, "🛑 收到终止信号，小红书多模态清洗已提前终止", "warning")
                # 将本轮未处理完成的笔记还原为 PENDING，允许下次安全继续清洗
                remaining_links = [r[0] for r in records[i:]]
                if remaining_links:
                    try:
                        with sqlite3.connect(DB_PATH, timeout=30.0) as conn_abort:
                            ph = ','.join(['?'] * len(remaining_links))
                            conn_abort.execute(f"UPDATE xhs_raw_posts SET clean_status = 'PENDING' WHERE post_link IN ({ph})", remaining_links)
                            conn_abort.commit()
                    except Exception as rollback_err:
                        print(f"❌ 回滚剩余笔记状态失败: {rollback_err}")
                break

            post_link = record[0]
            # pass the first 4 elements to process_single_post, publish_date is record[4]
            status, job_data = await process_single_post(record[:4], sse_task_id)
            publish_date = record[4]
        
            if status == "SUCCESS" and job_data:
                titles = []
                for j_idx, job in enumerate(job_data):
                    unique_link = f"{post_link}#job_{j_idx+1}" if len(job_data) > 1 else post_link
                    insert_to_raw_jobs(job, unique_link, publish_date)
                    titles.append(job.get('job_title', '未知岗位'))
                
                update_xhs_status(post_link, "SUCCESS")
                title_str = ", ".join(titles)
                print(f"✨ [{i+1}/{len(records)}] 清洗成功并入库 ({len(job_data)}个岗位): {title_str}\n")
                await push_sse_message(sse_task_id, f"✨ 成功转为标准职位入库 ({len(job_data)}个岗位): {title_str}")
            elif status == "NOT_A_JOB":
                update_xhs_status(post_link, "NOT_A_JOB")
                print(f"⚠️ [{i+1}/{len(records)}] 过滤非招聘笔记\n")
                await push_sse_message(sse_task_id, "⚠️ 鉴定为生活/非招聘笔记，已被自动丢弃")
            else:
                update_xhs_status(post_link, "FAILED")
                print(f"❌ [{i+1}/{len(records)}] 清洗失败\n")
                await push_sse_message(sse_task_id, "❌ 清洗失败", "error")
            
            # 同步进度条
            await push_sse_progress(sse_task_id, i + 1, len(records))
            
        print("🎉 本轮小红书清洗任务结束！\n")
        await push_sse_message(sse_task_id, "🎉 本轮笔记清洗完毕！")

if __name__ == "__main__":
    asyncio.run(run_vision_cleaner())
