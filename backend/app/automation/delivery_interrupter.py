"""
投递活跃执行打断管理器 (Delivery Interrupter)
==============================================
负责在多平台自动投递过程中，安全注册与触发正在操作的活跃浏览器标签页/Page 对象的打断钩子。
当用户在指挥中心点击「终止投递」或看门狗触发超时时，能够立即调用该钩子破门关闭当前操作页面，
迫使底层阻塞的网络等待或元素查找立即抛出连接/标签页关闭异常退出，安全释放全局串行互斥锁。
"""
import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_active_targets: dict[str, Callable[[], None]] = {}


def register_delivery_target(record_id: str, interrupt_fn: Callable[[], None]) -> None:
    """
    注册当前岗位活跃投递页面的打断回调。
    平台执行器在打开浏览器操作页面后调用。
    """
    if not record_id or not callable(interrupt_fn):
        return
    with _lock:
        rid = str(record_id)
        _active_targets[rid] = interrupt_fn
        logger.info(f"🎯 [delivery_interrupter] 已注册岗位 {rid} 的活跃打断钩子")


def unregister_delivery_target(record_id: str) -> None:
    """
    注销当前岗位活跃投递页面的打断回调。
    平台执行器在 finally 收尾阶段调用。
    """
    if not record_id:
        return
    with _lock:
        rid = str(record_id)
        _active_targets.pop(rid, None)
        logger.debug(f"🎯 [delivery_interrupter] 已注销岗位 {rid} 的打断钩子")


def interrupt_active_job(record_id: str) -> bool:
    """
    触发对指定活跃岗位的强制破门打断。
    如果该岗位当前正在活跃投递中且有注册钩子，立即执行打断并返回 True；
    若未注册（如尚未打开网页或已执行完毕），安全返回 False（严格 no-op 语义）。
    """
    if not record_id:
        return False

    target_fn: Callable[[], None] | None = None
    with _lock:
        rid = str(record_id)
        target_fn = _active_targets.get(rid)

    if target_fn:
        try:
            logger.warning(f"🛑 [delivery_interrupter] 正在对岗位 {record_id} 执行活跃浏览器破门打断...")
            target_fn()
            logger.info(f"✅ [delivery_interrupter] 岗位 {record_id} 破门打断已成功触发")
            return True
        except Exception as e:
            logger.error(f"❌ [delivery_interrupter] 触发岗位 {record_id} 破门打断异常: {e}")
            return False
    return False


def make_page_interrupt_fn(get_page_target: Callable[[], Any]) -> Callable[[], None]:
    """
    通用平台打断回调生成工厂：
    - 若有多个子标签页，强制关闭最新操作标签页；
    - 若为单标签页，先 stop_loading，再导航至 about:blank，强制打断网络请求与元素轮询。
    """
    def _interrupt():
        try:
            page = get_page_target()
            if not page:
                return
            if hasattr(page, "stop_loading"):
                try:
                    page.stop_loading()
                except Exception:
                    pass
            if hasattr(page, "tab_ids") and len(page.tab_ids) > 1:
                try:
                    page.get_tab(page.latest_tab).close()
                    return
                except Exception:
                    pass
            if hasattr(page, "get"):
                try:
                    page.get("about:blank")
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"⚠️ [delivery_interrupter] 执行页面打断细节异常: {e}")

    return _interrupt
