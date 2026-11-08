"""抓取日志「重复跳过」行识别（纯函数，零重依赖，pytest 直接单测）。

四平台采集器全部以 Popen 子进程运行，查重跳过信息只走 stdout（boss_collector.py:355/398、
51job_collector.py:253、liepin_crawler.py:505、zhilian_collector.py:831/819），各平台
controller 逐行解析 stdout 时用本函数把「重复跳过」行折算成跳过条数，经 SSE
scrape_progress 事件送到前端实时抓取流水横幅。

口径：只计「与库内已有岗位重复」；liepin 过期拦截（:499，180 天陈旧）与
zhilian 无法获取职位信息（:826，解析失败）不属于重复，不计数。
51job INSERT OR IGNORE 静默兜底（链接重复但三元组不同的罕见漏判）无 stdout 行，不可计。
"""
import re

# 智联「极速跃迁」整批全重复行：⏩ [极速跃迁] 第 N 批 (X/X 岗位均已在库，跳过详情解析)
_ZHILIAN_BATCH_RE = re.compile(r"\(\s*(\d+)\s*/\s*\d+\s*岗位均已在库")


def count_duplicate_skip(line: str) -> int:
    """单行日志命中的重复跳过条数；未命中返回 0。一行至多属于一个平台的一种模式。"""
    if not line:
        return 0
    count = 0
    if "数据库已存在，跳过" in line:  # boss_collector / zhilian_collector 前置查重拦截
        count += 1
    if "链接已存在，跳过" in line:  # boss_collector 落库时 INSERT OR IGNORE 兜底
        count += 1
    if "(已在库)" in line:  # 51job_collector 前置查重拦截
        count += 1
    if "跳过已收录" in line:  # liepin_crawler 前置查重拦截
        count += 1
    m = _ZHILIAN_BATCH_RE.search(line)  # zhilian 极速跃迁：整批均为历史旧岗位
    if m:
        count += int(m.group(1))
    return count
