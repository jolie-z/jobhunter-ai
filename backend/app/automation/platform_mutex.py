"""
平台级「抓取 ↔ 投递」在飞互斥（进程内事实源）。

背景（2026-10-29 Windows 0.4.0 沙箱事故）：抓取器与投递引擎共用同平台同调试端口的
Edge 实例，此前只有投递之间互斥（workflow._delivery_serial_lock，注释原话
"串行锁只防浏览器打架"），抓取与投递之间无任何互斥。09:00 定时全自动链路的抓取阶段
撞上手动投递批次：猎聘抓取器 attach 同一浏览器后把正在上传简历的标签页导航走
（liepin_crawler._check_login_status 无脑 page.get 首页），上传中断报废；51job 同
浏览器高频抓详情页触发风控滑块，会话级拦截后续投递。

设计：
- 双侧登记 + 单条件变量：同平台「抓取在飞」与「投递在飞」不得同时成立。
  投递先到先得，抓取限时等待后仍忙则放弃本轮派发（下轮波次/续抓自动补抓）；
  抓取先到，投递限时等待后仍忙则按 [环境] 暂时性失败返回（保留待投递门牌自愈重试）。
- 粒度：平台级、逐次操作。投递按岗获取/释放，同平台逐岗之间锁存在空隙，
  抓取可趁隙插入——浏览器空闲窗即人类行为间隙，不必也不应追求全程独占。
- 仅进程内：进程崩溃登记即清零，无需持久化；超时放行不强制抢占（宁可本轮跳过，
  不制造第二次撞车）。
- 平台名归一：workflow 的 platform 是 "boss/猎聘/liepin/51job/前程无忧/智联/zhilian"
  混杂口径，调度侧是 "boss/liepin/51job/zhilian"，统一收敛到后者。
"""

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# 抓取等待投递清场的默认上限：全自动链路投递批次逐岗串行，单岗 1-3 分钟，
# 10 分钟足以覆盖常见的手动批次；超时即放弃本轮派发并如实广播原因
SCRAPE_WAIT_DELIVERY_TIMEOUT_S = 600.0
# 投递等待抓取清场的默认上限：单轮派发抓取通常 1-4 分钟，5 分钟仍不结束视为
# 卡死抓取，投递按 [环境] 暂时性失败出列自愈重试，不与抓取抢浏览器
DELIVERY_WAIT_SCRAPE_TIMEOUT_S = 300.0
# 辅助浏览器操作（死链预检/存活检测）等待引擎清场的上限：预检逐条为 0 等待（非阻塞），
# 存活检测批级拿锁用它（等待引擎清场 90s 后整批取消）。先到先得 + 有限超时语义。
AUXILIARY_WAIT_TIMEOUT_S = 90.0

# 平台别名 → 调度侧规范键。未知平台返回 ""（调用方跳过互斥，行为与旧版一致）
_PLATFORM_ALIASES = {
    "boss": "boss",
    "boss直聘": "boss",
    "liepin": "liepin",
    "猎聘": "liepin",
    "51job": "51job",
    "前程无忧": "51job",
    "zhilian": "zhilian",
    "智联": "zhilian",
    "智联招聘": "zhilian",
}


def normalize_platform(raw: str) -> str:
    """平台别名归一到调度侧规范键；未识别返回空串。

    精确命中优先；未命中走双向包含匹配——workflow 的 platform 标签是子串口径
    （"boss" in platform / "猎聘" in platform），实际值无法穷举（如 "猎聘网"、
    组合标签），精确表漏网即静默旁路互斥（外审 round1 P1）。包含匹配的误报面
    （如 "aboss" 归 boss）无实际标签，可接受。
    """
    text = str(raw or "").strip().lower()
    if not text:
        return ""
    hit = _PLATFORM_ALIASES.get(text)
    if hit:
        return hit
    for alias, key in _PLATFORM_ALIASES.items():
        if alias in text or text in alias:
            return key
    return ""


# 平台 → 四类在飞登记槽：
#   scrape/deliver = 引擎层在飞（_run_*_task / delivery_node 闸门持有）
#   preflight      = 预检 DOM 判定短租约（秒级持有；外审 round4 P1-2：独立于引擎槽，
#                    杜绝预检覆盖引擎登记导致对侧提前放行再撞车）
#   aux            = 辅助浏览器操作（死链预检逐条 / 存活检测整批；round4 R9 收口）。
#                    先到先得 + 有限超时：aux 等引擎全部清场才动手；引擎也等 aux
#                    （aux 批级持有上限 240s，引擎闸门 120/300s 超时自愈重试——
#                    手动辅助工具与自动链路相撞时引擎走暂时性失败自愈，绝不共享浏览器）。
# 阻塞矩阵 _BLOCKERS：各类获取需等待的槽集合（含自身 → 同 kind 单槽不覆盖，无循环等待）
_busy: dict[str, dict[str, str | None]] = {}

# 条件变量按运行循环懒创建：uvicorn 生产恒单循环无感；测试框架每个用例独立循环，
# 模块级单例会绑定首个循环导致后续用例 RuntimeError(bound to a different event loop)
_cond: asyncio.Condition | None = None
_cond_loop: asyncio.AbstractEventLoop | None = None


def _get_cond() -> asyncio.Condition:
    global _cond, _cond_loop
    loop = asyncio.get_running_loop()
    if _cond is None or _cond_loop is not loop:
        _cond = asyncio.Condition()
        _cond_loop = loop
    return _cond


_BLOCKERS: dict[str, tuple[str, ...]] = {
    # 自身入矩阵（round4-P1-3）：同 kind 单槽只能一个持有者——第二个获取者等待/超时，
    # 杜绝"第二个覆盖第一个 token、第一个仍在飞时槽被提前清空"。调度层（crawlers
    # _platform_running_tasks / workflow inflight）虽已保证同平台同 kind 串行，互斥层
    # 自防不依赖上层纪律。
    "scrape": ("scrape", "deliver", "preflight", "aux"),
    "deliver": ("scrape", "deliver", "preflight", "aux"),
    "preflight": ("scrape", "deliver", "preflight", "aux"),
    "aux": ("scrape", "deliver", "preflight", "aux"),
}


def _state(key: str) -> dict[str, str | None]:
    return _busy.setdefault(key, {"scrape": None, "deliver": None, "preflight": None, "aux": None})


def is_scrape_busy(raw_platform: str) -> bool:
    key = normalize_platform(raw_platform)
    return bool(key) and _state(key)["scrape"] is not None


def is_delivery_busy(raw_platform: str) -> bool:
    key = normalize_platform(raw_platform)
    return bool(key) and _state(key)["deliver"] is not None


def is_aux_busy(raw_platform: str) -> bool:
    """辅助浏览器操作（死链预检/存活检测批次）在飞？供批级预探与观测。"""
    key = normalize_platform(raw_platform)
    return bool(key) and _state(key)["aux"] is not None


def busy_snapshot() -> dict[str, dict[str, str | None]]:
    """当前在飞登记快照（观测/日志用）。返回 {规范平台键: {"scrape": owner, "deliver": owner}}。"""
    return {k: dict(v) for k, v in _busy.items() if any(v.values())}


async def _acquire(kind: str, key: str, owner: str, timeout_s: float) -> str | None:
    """获取某类操作的在飞登记。按 _BLOCKERS 矩阵等待互斥槽清场，超时返回 None（不抢占）。

    成功返回**本次获取的唯一 token**（round3-P1-2 修正）：槽内存 token 而非 owner——
    同名 owner 重复获取（如固定名 liveness:zhilian 的先后两批）时，旧批的延迟释放
    凭 token 校验失败，不会误清新批的锁。等待阶段不持有任何登记。"""
    blockers = _BLOCKERS[kind]
    deadline = time.monotonic() + max(0.0, timeout_s)
    async with _get_cond():
        while any(_state(key)[b] is not None for b in blockers):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                await asyncio.wait_for(_get_cond().wait(), timeout=remaining)
            except asyncio.TimeoutError:
                return None
        token = f"{owner or kind}#{uuid.uuid4().hex[:8]}"
        _state(key)[kind] = token
        return token


async def _release(kind: str, key: str, token: str) -> None:
    """按 token 释放在飞登记并唤醒所有等待者。

    token 必填且须与槽内登记精确一致（round3-P1-2）：同名 owner 的先后两次获取
    token 不同，旧持有者的延迟释放校验失败被拒，绝不误清新持有者的锁。"""
    async with _get_cond():
        state = _state(key)
        current = state[kind]
        if current is None:
            return
        if not token or current != token:
            logger.warning(
                f"[platform_mutex] 释放登记 token 不匹配，已忽略：{key}/{kind} "
                f"持有者={current}，请求方={token or '<空>'}（防误清新持有者的锁）")
            return
        state[kind] = None
        _get_cond().notify_all()


async def acquire_scrape(raw_platform: str, owner: str = "",
                         timeout_s: float = SCRAPE_WAIT_DELIVERY_TIMEOUT_S) -> bool:
    """抓取侧登记：同平台投递在飞时限时等待，超时返回 False（调用方应跳过本轮派发）。"""
    key = normalize_platform(raw_platform)
    if not key:
        return True  # 未纳管平台（如小红书）不设防，行为与旧版一致
    return await _acquire("scrape", key, owner, timeout_s)


async def release_scrape(raw_platform: str, owner: str = "", token: str = "") -> None:
    """owner 仅观测用途（日志/tag 前缀）；释放以 token 精确校验为准，空 token no-op。"""
    key = normalize_platform(raw_platform)
    if key and token:
        await _release("scrape", key, token)
    elif key and not token:
        logging.getLogger(__name__).debug(
            f"[platform_mutex] release_scrape 空 token no-op：{key} owner={owner or '<空>'}")


async def acquire_delivery(raw_platform: str, owner: str = "",
                           timeout_s: float = DELIVERY_WAIT_SCRAPE_TIMEOUT_S) -> bool:
    """投递侧登记：同平台抓取在飞时限时等待，超时返回 False（调用方按暂时性失败出列）。"""
    key = normalize_platform(raw_platform)
    if not key:
        return True
    return await _acquire("deliver", key, owner, timeout_s)


async def release_delivery(raw_platform: str, owner: str = "", token: str = "") -> None:
    """owner 仅观测用途（日志/tag 前缀）；释放以 token 精确校验为准，空 token no-op。"""
    key = normalize_platform(raw_platform)
    if key and token:
        await _release("deliver", key, token)
    elif key and not token:
        logging.getLogger(__name__).debug(
            f"[platform_mutex] release_delivery 空 token no-op：{key} owner={owner or '<空>'}")


def delivery_gate_timeout_error(timeout_s: float = DELIVERY_WAIT_SCRAPE_TIMEOUT_S) -> str:
    """投递闸门超时的统一错误文案（workflow 产出与失败分诊测试共用，防文案漂移）。

    [环境] 前缀 → failure_triage 归 transient → 保留飞书「待投递」门牌自愈重试；
    改文案必须同步 test_gate_timeout_failure_semantics。
    """
    return (f"❌ [环境] 平台抓取任务正在占用浏览器，投递延后自愈重试"
            f"（等待清场超 {timeout_s:.0f}s）")


@asynccontextmanager
async def preflight_lease(raw_platform: str, owner: str = "preflight",
                          wait_timeout_s: float = 30.0):
    """预检短租约（外审 round3-P1 / round4-P1 修正版）：包住预检 DOM 登录判定的秒级
    窗口，关闭预检导航与在飞引擎的 TOCTOU 撞车窗。

    - 独立 preflight 槽（不与引擎 scrape/deliver 同槽，杜绝覆盖引擎登记）；
    - 阻塞矩阵：等待全部引擎槽与其它 preflight 租约清场；对侧在飞 → 等待超时
      yield False，调用方必须据此放弃导航（存疑放行），绝不带 False 硬闯；
    - 等待阶段不持有任何登记，不阻塞对侧引擎派发。
    """
    key = normalize_platform(raw_platform)
    if not key:
        yield True
        return
    token = await _acquire("preflight", key, owner, wait_timeout_s)
    ok = token is not None
    try:
        yield ok
    finally:
        if ok:
            await _release("preflight", key, token)


async def acquire_auxiliary(raw_platform: str, owner: str,
                            timeout_s: float | None = None) -> bool:
    """辅助操作批级登记（存活检测整批持有用）；等待引擎清场，超时 False。

    owner 必填（round1-P2）：空 owner 会在释放时被拒绝（防误清语义），等于登记泄漏。
    timeout_s=None 时运行时读模块常量（默认参数定义时求值，测试 patch 将失效）。"""
    key = normalize_platform(raw_platform)
    if not key:
        return True
    if timeout_s is None:
        timeout_s = AUXILIARY_WAIT_TIMEOUT_S
    return await _acquire("aux", key, owner, timeout_s)


async def release_auxiliary(raw_platform: str, owner: str, token: str) -> None:
    """释放 aux 位。token 必填（acquire_auxiliary 返回值），精确校验防误清新持有者。"""
    key = normalize_platform(raw_platform)
    if key and token:
        await _release("aux", key, token)
    elif key:
        logging.getLogger(__name__).warning(
            f"[platform_mutex] release_auxiliary 缺 token，已忽略：{key} owner={owner or '<空>'}")


@asynccontextmanager
async def auxiliary_gate(raw_platform: str, owner: str,
                         wait_timeout_s: float | None = None):
    """辅助浏览器操作闸门（contextmanager 形式，仅用于「协程内无线程」的短持有场景，
    如存活检测批级持有——inner 体全部 await，协程活着=持锁期内无孤儿线程）。

    语义：独立 aux 槽，阻塞矩阵对 scrape/deliver/preflight/aux 全互斥（先到先得 +
    有限超时 + 各自既有语义收场，无"谦让"单向语义）。token 化（round3-P1-2）：
    acquire 返回唯一 token，release 精确校验，同名 owner 的先后获取互不误清。
    取消收场（round3-P1-1''）：协程被取消时 shield+同步兜底清 aux 位——仅适用于
    「协程内无后台线程」场景；涉及 to_thread 同步检测的调用方必须改用
    run_with_aux（释放挂线程 done-callback，取消不放锁）。

    ⚠️ 当前无调用方（round6-P2-e 口径）：precheck 已改走 run_with_aux，存活检测
    走 acquire_auxiliary 便捷函数。本 CM 保留为「协程内无线程持有」场景的预留
    接口——若用于含 to_thread 的流程，取消收场的清位会在线程结束前放锁（R9 同源
    风险），届时必须迁移到 run_with_aux。
    """
    key = normalize_platform(raw_platform)
    if not key:
        yield True
        return
    if wait_timeout_s is None:
        wait_timeout_s = AUXILIARY_WAIT_TIMEOUT_S
    token = await _acquire("aux", key, owner, wait_timeout_s)
    ok = token is not None
    try:
        yield ok
    finally:
        if ok:
            # 取消安全（仅协程内无线程场景成立）：shield 保证释放完成；连 shield 都被取消
            # （循环关闭）则同步清 aux 位兜底——token 精确校验，不误清新持有者。
            import asyncio as _aio
            try:
                await _aio.shield(_release("aux", key, token))
            except _aio.CancelledError:
                state = _state(key)
                if state["aux"] == token:
                    state["aux"] = None


def _release_aux_now(key: str, token: str) -> None:
    """在事件循环线程里按 token 释放 aux 并唤醒等待者；循环已关闭时同步清位兜底。

    只清自己 token（round4-P2-d）：绝不误清同平台其它类的登记或新持有者。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        state = _state(key)
        if state["aux"] == token:
            state["aux"] = None
        return
    try:
        loop.create_task(_release("aux", key, token))
    except RuntimeError:
        state = _state(key)
        if state["aux"] == token:
            state["aux"] = None


async def run_with_aux(sync_fn, raw_platform: str, owner: str,
                       *args, _wait_timeout_s: float | None = None, **kwargs):
    """辅助浏览器操作终版入口（round4-P1-1'' / round5-P1-1 修正）：
    同步函数在线程里跑，aux 位的释放挂在**底层线程 future** 的 done callback——
    线程活着 aux 必在，引擎闸门（阻塞矩阵含 aux）在线程结束前无法进入。

    取消语义：外层用 `await asyncio.shield(fut)`——协程被 cancel 时只中断等待，
    fut 不被取消、线程继续跑，done callback 在线程真正结束后才释放 aux。因此
    正常/取消/异常三条路径的「线程-锁生命周期」精确同步，R9 撞页窗全部关闭。
    （round5-P1-1：旧实现 `await fut` 会被 Task 连带 cancel 掉 asyncio Future，
    回调提前触发、锁在线程结束前就被放掉。）

    Returns: sync_fn 的返回值；闸门被引擎占用时返回 None（调用方按「无法判定」收场）。
    """
    key = normalize_platform(raw_platform)
    if not key:
        return await asyncio.to_thread(sync_fn, *args, **kwargs)
    if _wait_timeout_s is None:
        _wait_timeout_s = AUXILIARY_WAIT_TIMEOUT_S
    token = await _acquire("aux", key, owner, _wait_timeout_s)
    if token is None:
        return None  # 引擎在飞：非阻塞拒绝（调用方既有「无法判定」语义）

    loop = asyncio.get_running_loop()
    try:
        fut = loop.run_in_executor(None, lambda: sync_fn(*args, **kwargs))
    except BaseException:
        # 线程根本没起来（executor 已 shutdown 等）：没有残留线程，按 token 安全释放
        await asyncio.shield(_release("aux", key, token))
        raise
    # 线程结束 → 回调按 token 释放 aux 并 notify_all 唤醒等待者。回调由事件循环
    # 调度，运行在循环线程；不预先清槽，_release 走完整「校验 + notify_all」路径
    # （round5-P1-2：旧实现先同步清位，导致 _release 早退、等待者永远不被唤醒）。
    fut.add_done_callback(lambda _f: _release_aux_now(key, token))
    return await asyncio.shield(fut)


@asynccontextmanager
async def scrape_gate(raw_platform: str, owner: str = "",
                      timeout_s: float = SCRAPE_WAIT_DELIVERY_TIMEOUT_S):
    """抓取闸门：yield 是否成功获得登记；未获得时调用方自行跳过。"""
    key = normalize_platform(raw_platform)
    if not key:
        yield True
        return
    token = await _acquire("scrape", key, owner, timeout_s)
    ok = token is not None
    try:
        yield ok
    finally:
        if ok:
            await _release("scrape", key, token)


@asynccontextmanager
async def delivery_gate(raw_platform: str, owner: str = "",
                        timeout_s: float = DELIVERY_WAIT_SCRAPE_TIMEOUT_S):
    """投递闸门：yield 是否成功获得登记；未获得时调用方按暂时性失败处理。"""
    key = normalize_platform(raw_platform)
    if not key:
        yield True
        return
    token = await _acquire("deliver", key, owner, timeout_s)
    ok = token is not None
    try:
        yield ok
    finally:
        if ok:
            await _release("deliver", key, token)


async def wait_delivery_clear(raw_platform: str, timeout_s: float = SCRAPE_WAIT_DELIVERY_TIMEOUT_S) -> bool:
    """抓取侧派发前守卫：等待同平台投递清场。True=已清场可派发；False=超时仍忙（应跳过本轮）。

    与 scrape_gate 的分工：编排层 worker 在派发前用它做长时间冷静等待并广播进度，
    真正的互斥登记由 _run_*_task 内的 scrape_gate 兜底（两者登记口径一致，可叠加）。
    """
    key = normalize_platform(raw_platform)
    if not key:
        return True
    deadline = time.monotonic() + max(0.0, timeout_s)
    async with _get_cond():
        while _state(key)["deliver"] is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                await asyncio.wait_for(_get_cond().wait(), timeout=remaining)
            except asyncio.TimeoutError:
                return False
    return True


def reset_platform(raw_platform: str) -> None:
    """同步清空指定平台全部登记（异常兜底用：取消链打断异步释放时防槽位泄漏）。

    仅应在持有者已确定终止（任务取消/协程退出）后调用——它不校验 owner，
    会无差别清空该平台四槽。同步设计（round2-P2 说明）：调用场景是事件循环
    关闭/取消链断裂，此刻无法安全 await notify；既有等待者均有有限超时
    （90/120/300/600s），最坏按各自超时醒来重探（重探看到槽位已空即放行），
    不会永久阻塞。"""
    key = normalize_platform(raw_platform)
    if key:
        _busy.pop(key, None)


def reset_for_test() -> None:
    """仅测试用：清空全部登记与条件变量缓存。"""
    global _cond, _cond_loop
    _busy.clear()
    _cond = None
    _cond_loop = None
