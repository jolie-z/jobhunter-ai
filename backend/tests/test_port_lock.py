"""跨进程 CDP 端口锁单测（矩阵⑦配套）。

背景：矩阵⑦允许 dev 实例附着桌面版浏览器后，两个后端可能同时驱动同一 Edge。
进程内 platform_mutex 管不到另一个进程，故用文件锁（POSIX flock / Windows
msvcrt）做跨进程串行；锁被占用时采集器以 75 退出、投递返回 False 延后重试。

2026-10-31 复审补齐：同进程双 fd 会自锁，因此 acquire_port_lock 增加进程内
每端口 RLock 注册表 + 同线程重入 depth；本文件覆盖重入、跨线程竞争、msvcrt
错误分类、无锁原语 fail-open、相对锁目录归一、超时环境变量、async 拒绝。
"""
import errno
import logging
import os
import sys
import threading
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import engine_guard as eg  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_lock_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBHUNTER_CDP_LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.delenv("JOBHUNTER_CDP_LOCK_TIMEOUT_S", raising=False)
    yield


class _Holder:
    """在独立线程持有端口锁，供 busy/竞争测试使用。"""

    def __init__(self, port, platform, timeout_s=0.5):
        self.port = port
        self.platform = platform
        self.timeout_s = timeout_s
        self.ready = threading.Event()
        self.stop = threading.Event()
        self.fd = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        self.fd = eg.acquire_port_lock(self.port, self.platform, timeout_s=self.timeout_s, poll_s=0.01)
        self.ready.set()
        self.stop.wait(3)
        # RLock 有线程归属：必须在持有线程内释放，不能交给主线程
        if self.fd is not None:
            eg.release_port_lock(self.fd)
            self.fd = None

    def __enter__(self):
        self.thread.start()
        assert self.ready.wait(2), "holder 未能取得锁"
        assert self.fd is not None and self.fd >= 0
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join(3)


def test_acquire_release_and_same_thread_reentry():
    """同线程重入复用同一 fd；跨线程第二次获取在本地锁上超时。"""
    fd1 = eg.acquire_port_lock(19222, "boss", timeout_s=0.1, poll_s=0.01)
    assert fd1 is not None and fd1 >= 0
    try:
        fd2 = eg.acquire_port_lock(19222, "boss", timeout_s=0.1, poll_s=0.01)
        assert fd2 == fd1  # 重入，不再次 open/flock
        eg.release_port_lock(fd2)  # depth 2->1，文件锁仍持有

        result = []
        t = threading.Thread(
            target=lambda: result.append(
                eg.acquire_port_lock(19222, "boss", timeout_s=0.1, poll_s=0.01)
            ),
            daemon=True,
        )
        t.start()
        t.join(2)
        assert result == [None]
    finally:
        eg.release_port_lock(fd1)

    fd3 = eg.acquire_port_lock(19222, "boss", timeout_s=0.2, poll_s=0.01)
    assert fd3 is not None and fd3 >= 0
    eg.release_port_lock(fd3)


def test_different_ports_do_not_block_each_other():
    """锁粒度是端口：BOSS 抓取不应阻塞 51job 投递。"""
    fd_boss = eg.acquire_port_lock(19222, "boss", timeout_s=0.1, poll_s=0.01)
    try:
        fd_51 = eg.acquire_port_lock(9227, "51job", timeout_s=0.1, poll_s=0.01)
        assert fd_51 is not None and fd_51 >= 0
        eg.release_port_lock(fd_51)
    finally:
        eg.release_port_lock(fd_boss)


def test_decorator_exit_on_busy():
    """采集器语义：锁被占用时以 75（EX_TEMPFAIL）退出，供调度器中性跳过。"""
    with _Holder(9227, "51job"):
        @eg.cross_process_port_lock(9227, "51job", timeout_s=0.05, on_busy="exit")
        def _run():
            raise AssertionError("锁被占用时不应执行函数体")

        with pytest.raises(SystemExit) as ei:
            _run()
        assert ei.value.code == eg.PORT_LOCK_BUSY_EXIT_CODE


def test_decorator_false_sets_delivery_error():
    """投递语义：锁被占用时返回 False 并写入 delivery_error（失败分诊按暂时性重试）。"""
    with _Holder(9226, "liepin"):
        @eg.cross_process_port_lock(9226, "liepin", timeout_s=0.05, on_busy="false")
        def _deliver(_job_data):
            raise AssertionError("锁被占用时不应执行函数体")

        job = {}
        assert _deliver(job) is False
        assert "正被占用" in job["delivery_error"]


def test_decorator_false_missing_payload_logs(caplog):
    """on_busy=false 找不到 dict payload 时必须留 WARNING，不能静默丢原因。"""
    with _Holder(9250, "zhilian"):
        @eg.cross_process_port_lock(9250, "zhilian", timeout_s=0.05, on_busy="false")
        def _deliver(_payload):
            raise AssertionError("锁被占用时不应执行函数体")

        with caplog.at_level(logging.WARNING, logger="engine_guard"):
            assert _deliver("not-a-dict") is False
        assert "未找到 job_data dict" in caplog.text


def test_decorator_raises_and_releases_on_exception():
    """异常路径必须释放锁，否则平台端口会被永久占住。"""
    @eg.cross_process_port_lock(19222, "boss", timeout_s=0.1)
    def _boom():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        _boom()

    fd = eg.acquire_port_lock(19222, "boss", timeout_s=0.2, poll_s=0.01)
    assert fd is not None and fd >= 0
    eg.release_port_lock(fd)


def test_decorator_rejects_async_and_generator():
    """async/生成器会在 await/yield 期间释放锁，装饰时必须直接拒绝。"""
    with pytest.raises(TypeError):
        @eg.cross_process_port_lock(19222, "boss")
        async def _async_entry():
            return None

    with pytest.raises(TypeError):
        @eg.cross_process_port_lock(19222, "boss")
        def _gen_entry():
            yield None


def test_msvcrt_busy_vs_facility_error(tmp_path):
    """Windows: EACCES/EDEADLOCK=被占用；EBADF 等设施故障必须上抛走 fail-open。"""
    class FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 0

        def __init__(self, err):
            self.err = err

        def locking(self, fd, mode, n):
            raise OSError(self.err, "fake")

    fd = os.open(tmp_path / "fake.lock", os.O_RDWR | os.O_CREAT)
    old_fcntl, old_msvcrt = eg.fcntl, eg.msvcrt
    try:
        eg.fcntl = None
        eg.msvcrt = FakeMsvcrt(errno.EACCES)
        assert eg._try_flock(fd) is False
        eg.msvcrt = FakeMsvcrt(errno.EBADF)
        with pytest.raises(OSError):
            eg._try_flock(fd)
    finally:
        eg.fcntl, eg.msvcrt = old_fcntl, old_msvcrt
        os.close(fd)


def test_no_lock_primitives_fail_open(monkeypatch):
    """既无 fcntl 也无 msvcrt 时必须返回 -1 + WARNING，不能假装持锁。"""
    monkeypatch.setattr(eg, "fcntl", None)
    monkeypatch.setattr(eg, "msvcrt", None)
    assert eg.acquire_port_lock(19222, "boss", timeout_s=0.01) == -1


def test_relative_lock_dir_normalized(monkeypatch, tmp_path):
    """JOBHUNTER_CDP_LOCK_DIR 相对路径必须 abspath，否则不同 cwd 各拿各的锁。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JOBHUNTER_CDP_LOCK_DIR", "relative-locks")
    path = eg._port_lock_path(19222)
    assert os.path.isabs(path)
    assert str(tmp_path) in path


def test_timeout_env_override(monkeypatch):
    """默认超时可由 JOBHUNTER_CDP_LOCK_TIMEOUT_S 覆盖；显式参数优先。"""
    monkeypatch.setenv("JOBHUNTER_CDP_LOCK_TIMEOUT_S", "0.1")
    assert eg._resolve_lock_timeout(None) == pytest.approx(0.1)
    assert eg._resolve_lock_timeout(5) == 5


def test_timeout_rejects_non_finite(monkeypatch):
    """env 的 inf/nan 回落默认；显式非法 timeout_s 是调用方 bug，直接抛 ValueError。"""
    monkeypatch.setenv("JOBHUNTER_CDP_LOCK_TIMEOUT_S", "inf")
    assert eg._resolve_lock_timeout(None) == eg._PORT_LOCK_TIMEOUT_S
    monkeypatch.setenv("JOBHUNTER_CDP_LOCK_TIMEOUT_S", "nan")
    assert eg._resolve_lock_timeout(None) == eg._PORT_LOCK_TIMEOUT_S
    with pytest.raises(ValueError):
        eg._resolve_lock_timeout(float("inf"))
    with pytest.raises(ValueError):
        eg._resolve_lock_timeout("abc")


def test_invalid_on_busy_rejected():
    """on_busy 非法值必须在装饰期报错，不能静默走 raise 分支。"""
    with pytest.raises(ValueError):
        eg.cross_process_port_lock(19222, "boss", on_busy="bogus")


def test_keyboard_interrupt_releases_local_lock(monkeypatch):
    """轮询期间 KeyboardInterrupt 必须归还本地 RLock，否则端口永久中毒。"""
    def _boom(_fd):
        raise KeyboardInterrupt()

    with monkeypatch.context() as m:
        m.setattr(eg, "_try_flock", _boom)
        with pytest.raises(KeyboardInterrupt):
            eg.acquire_port_lock(19222, "boss", timeout_s=0.1, poll_s=0.01)

    fd = eg.acquire_port_lock(19222, "boss", timeout_s=0.2, poll_s=0.01)
    assert fd is not None and fd >= 0
    eg.release_port_lock(fd)


def test_release_from_wrong_thread_rejected(caplog):
    """跨线程释放必须拒绝且不产生副作用（文件锁仍由 owner 持有）。"""
    fd = eg.acquire_port_lock(19222, "boss", timeout_s=0.1, poll_s=0.01)
    assert fd is not None and fd >= 0
    try:
        with caplog.at_level(logging.ERROR, logger="engine_guard"):
            t = threading.Thread(target=lambda: eg.release_port_lock(fd), daemon=True)
            t.start()
            t.join(2)
        assert "跨线程释放被拒绝" in caplog.text

        # 强断言：文件锁仍被主线程持有——另开 fd 直接 flock 应失败
        probe_fd = os.open(eg._port_lock_path(19222), os.O_RDWR | os.O_CREAT)
        try:
            assert eg._try_flock(probe_fd) is False
        finally:
            os.close(probe_fd)

        result = []
        t2 = threading.Thread(
            target=lambda: result.append(
                eg.acquire_port_lock(19222, "boss", timeout_s=0.1, poll_s=0.01)
            ),
            daemon=True,
        )
        t2.start()
        t2.join(2)
        assert result == [None]  # 仍由主线程持有
    finally:
        eg.release_port_lock(fd)

    fd2 = eg.acquire_port_lock(19222, "boss", timeout_s=0.2, poll_s=0.01)
    assert fd2 is not None and fd2 >= 0
    eg.release_port_lock(fd2)


def test_double_release_is_noop(caplog):
    """重复释放不能盲目 close 已可能被 OS 复用的 fd。"""
    fd = eg.acquire_port_lock(19222, "boss", timeout_s=0.1, poll_s=0.01)
    assert fd is not None and fd >= 0
    eg.release_port_lock(fd)
    with caplog.at_level(logging.WARNING, logger="engine_guard"):
        eg.release_port_lock(fd)
    assert "未注册 fd" in caplog.text

    fd2 = eg.acquire_port_lock(19222, "boss", timeout_s=0.2, poll_s=0.01)
    assert fd2 is not None and fd2 >= 0
    eg.release_port_lock(fd2)


def test_reentry_interrupt_rolls_back_depth(monkeypatch):
    """重入 depth +1 后、handed_off 前被打断：必须回滚 depth，不能永久 +1。"""
    class _RaiseAfterSet(dict):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.armed = True

        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            if self.armed:
                self.armed = False
                raise KeyboardInterrupt()

    fd = eg.acquire_port_lock(19222, "boss", timeout_s=0.1, poll_s=0.01)
    assert fd is not None and fd >= 0
    original_depth = eg._local_depth
    custom = _RaiseAfterSet(original_depth)
    monkeypatch.setattr(eg, "_local_depth", custom)
    try:
        with pytest.raises(KeyboardInterrupt):
            eg.acquire_port_lock(19222, "boss", timeout_s=0.1, poll_s=0.01)
        assert custom.armed is False  # 注入确实命中了 depth 写入点
        assert custom.get(19222) == 1  # +1 已回滚
    finally:
        monkeypatch.setattr(eg, "_local_depth", original_depth)

    eg.release_port_lock(fd)
    fd2 = eg.acquire_port_lock(19222, "boss", timeout_s=0.2, poll_s=0.01)
    try:
        assert fd2 is not None and fd2 >= 0
    finally:
        eg.release_port_lock(fd2)


def test_fresh_interrupt_clears_fd_mapping(monkeypatch):
    """fresh 路径注册 fd 后、handed_off 前被打断：finally 必须清映射并释放本地锁。"""
    class _RaiseAfterSet(dict):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.armed = True
            self.last_fd = None

        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            if self.armed:
                self.armed = False
                self.last_fd = key
                raise KeyboardInterrupt()

    original_fd_ports = eg._fd_ports
    custom = _RaiseAfterSet(original_fd_ports)
    monkeypatch.setattr(eg, "_fd_ports", custom)
    try:
        with pytest.raises(KeyboardInterrupt):
            eg.acquire_port_lock(19222, "boss", timeout_s=0.1, poll_s=0.01)
        assert custom.last_fd is not None  # 注入确实命中 fd 注册点
        assert custom.last_fd not in custom  # 该 fd 已被 finally 清掉
    finally:
        monkeypatch.setattr(eg, "_fd_ports", original_fd_ports)

    fd = eg.acquire_port_lock(19222, "boss", timeout_s=0.2, poll_s=0.01)
    try:
        assert fd is not None and fd >= 0
    finally:
        eg.release_port_lock(fd)


def test_drop_local_state_clears_fd_mapping(tmp_path):
    """注册 fd 后、handed_off 前被打断：_drop_local_state 只清本端口映射。"""
    fd = os.open(tmp_path / "fake.lock", os.O_RDWR | os.O_CREAT)
    fd2 = os.open(tmp_path / "other.lock", os.O_RDWR | os.O_CREAT)
    local = threading.RLock()
    local.acquire()
    try:
        with eg._local_guard:
            eg._fd_ports[fd] = 999
            eg._fd_ports[fd2] = 888
        eg._drop_local_state(999, local)
        assert fd not in eg._fd_ports
        assert eg._fd_ports.get(fd2) == 888
    finally:
        with eg._local_guard:
            eg._fd_ports.pop(fd, None)
            eg._fd_ports.pop(fd2, None)
        os.close(fd)
        os.close(fd2)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX fcntl 分支仅在非 Windows 有意义")
def test_fcntl_busy_vs_facility_error(tmp_path):
    """POSIX: EAGAIN/EACCES=被占用；EBADF 等设施故障必须上抛走 fail-open。"""
    class FakeFcntl:
        LOCK_EX = 1
        LOCK_NB = 2
        LOCK_UN = 4

        def __init__(self, err):
            self.err = err

        def flock(self, fd, op):
            raise OSError(self.err, "fake")

    fd = os.open(tmp_path / "fake.lock", os.O_RDWR | os.O_CREAT)
    old_fcntl = eg.fcntl
    try:
        eg.fcntl = FakeFcntl(errno.EAGAIN)
        assert eg._try_flock(fd) is False
        eg.fcntl = FakeFcntl(errno.EACCES)
        assert eg._try_flock(fd) is False
        eg.fcntl = FakeFcntl(errno.EBADF)
        with pytest.raises(OSError):
            eg._try_flock(fd)
    finally:
        eg.fcntl = old_fcntl
        os.close(fd)


def test_lock_dir_unavailable_fail_open(tmp_path, monkeypatch):
    """锁设施不可用（目录不可创建）时 fail-open 返回 -1，不阻断业务。"""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    monkeypatch.setenv("JOBHUNTER_CDP_LOCK_DIR", str(blocker / "locks"))
    assert eg.acquire_port_lock(19222, "boss", timeout_s=0.01) == -1
