"""匿名功能使用计数器（0.4.7）——进程内存量、只存纯数字计数。

隐私边界（与 desktop/telemetry.js、telemetry/public/index.html 三方约定一致）：
  - 只记「某功能/某环节用了几次、成了几次、败了几次」这类纯数字；
  - 键是本模块写死的枚举码，绝不允许调用方传职位名/公司名/简历内容等任何自由文本；
  - 计数不出机器：不落盘、不随日志外发，仅经壳（desktop/main.js）定时拉取后
    并入匿名心跳批量上报，用户可在托盘随时关闭统计（关闭则壳不再拉取）。

数据流：pipeline/模块钩点 → bump() 内存累加
  → GET /api/v1/usage/local-counters（仅 127.0.0.1，无鉴权不出本机）
  → 壳随心跳带出 → 运营服务器按日聚合。

防膨胀：键数上限 USAGE_MAX_KEYS（超限静默丢弃新键；KNOWN_CODES 白名单本身
远小于上限，此防线只兜埋点写错码的意外）。多进程形态（uvicorn 单进程）下每进程一份即可。
"""
from __future__ import annotations

import threading

USAGE_MAX_KEYS = 64

_lock = threading.Lock()
_counters: dict[str, int] = {}

# 枚举码白名单（唯一事实源）：壳与运营看板的展示名映射各自维护，
# 这里把守「什么样的键允许进桶」。新增功能埋点先在此登记。
KNOWN_CODES = frozenset({
    # pipeline 环节（自动化链路）
    "pipeline_run",           # 全自动链路发射次数
    "pipeline_scraped",       # 本进程累计抓取入库岗位数
    "pipeline_cleaned",       # 流式清洗通过数（含收口）
    "pipeline_evaluated",     # 进入评估的岗位数
    "pipeline_delivered_ok",  # 投递成功岗位数
    "pipeline_delivered_fail",  # 投递失败岗位数
    # 手动模块使用
    "resume_print_pdf",       # 简历库手动导出 PDF
    "resume_print_images",    # 简历库手动导出长图
    "strategy_diagnosis",     # 策略实验室·全局诊断
    "strategy_greeting",      # 策略实验室·生成打招呼语
    "strategy_rewrite",       # 策略实验室·技能改写
    "strategy_ats",           # 策略实验室·ATS 对齐
    "job_import",             # 手动录入岗位
})


def _bump(code: str, n: int) -> None:
    if code not in KNOWN_CODES:
        return
    if n <= 0:
        # 显式传 0/负数 = 无事发生（空跑/零产出），绝不折算成 +1；无参调用默认 n=1
        return
    with _lock:
        if code not in _counters and len(_counters) >= USAGE_MAX_KEYS:
            return
        _counters[code] = _counters.get(code, 0) + n


def bump(code: str, n: int = 1) -> None:
    """累加计数；未知码静默丢弃（埋点写错码不该打崩业务链路）；n<=0 为无操作。"""
    try:
        _bump(code, n)
    except Exception:  # noqa: BLE001 — 计数器绝不反向影响业务
        pass


def snapshot() -> dict[str, int]:
    """当前计数只读快照（壳拉取用；不清零——进程生命周期内累计口径）。"""
    with _lock:
        return dict(_counters)


def reset_for_tests() -> None:
    """仅测试用：清空进程内计数（生产代码不得调用）。"""
    with _lock:
        _counters.clear()
