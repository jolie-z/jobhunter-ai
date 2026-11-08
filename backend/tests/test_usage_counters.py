"""usage_counters 单测：枚举码白名单、累计口径、快照只读、异常输入静默。

跑法：cd backend && python -m pytest tests/test_usage_counters.py -q
"""
from app.core import usage_counters as uc


def setup_function(_):
    uc.reset_for_tests()


def test_bump_known_codes_accumulate():
    uc.bump("pipeline_run")
    uc.bump("pipeline_run")
    uc.bump("pipeline_delivered_ok", 3)
    snap = uc.snapshot()
    assert snap["pipeline_run"] == 2
    assert snap["pipeline_delivered_ok"] == 3


def test_bump_unknown_code_silently_dropped():
    # 自由文本/写错码一律不进桶：这是「计数不含内容」承诺的实现面
    uc.bump("某公司Java岗位")
    uc.bump("not_in_whitelist")
    uc.bump("")
    assert uc.snapshot() == {}


def test_bump_non_positive_n_is_noop():
    # 0/负数 = 无事发生（空跑/零产出不得折算成 +1）；无参调用默认 n=1
    uc.bump("job_import", 0)
    uc.bump("job_import", -5)
    assert uc.snapshot() == {}
    uc.bump("job_import")
    assert uc.snapshot()["job_import"] == 1


def test_bump_never_raises():
    # n 为离谱类型也不能打崩业务调用方（Number 转换失败 → 静默丢弃该次）
    uc.bump("pipeline_run", "abc")
    assert uc.snapshot() == {}


def test_snapshot_is_copy():
    uc.bump("resume_print_pdf")
    snap = uc.snapshot()
    snap["resume_print_pdf"] = 999
    assert uc.snapshot()["resume_print_pdf"] == 1


def test_max_keys_cap():
    for i in range(200):
        # 白名单只有 15 个码，全打满后不再增长；这里验证桶上限逻辑不会被未知码绕过
        uc.bump(f"code_{i}")
    assert len(uc.snapshot()) == 0  # 全部是未知码，一个都不进
    for code in uc.KNOWN_CODES:
        uc.bump(code)
    assert len(uc.snapshot()) == len(uc.KNOWN_CODES)
