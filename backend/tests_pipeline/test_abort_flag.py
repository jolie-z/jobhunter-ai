"""终止开关（abort 模块）行为测试：begin 清理上轮标记、request/is/end 协作。"""
from app.automation import abort as abort_mod


def test_begin_clears_previous_abort():
    abort_mod.request_abort()
    assert abort_mod.is_aborted()
    abort_mod.begin_pipeline("pipeline_test1")
    assert not abort_mod.is_aborted()
    abort_mod.end_pipeline()


def test_request_abort_task_mismatch_ignored():
    abort_mod.begin_pipeline("pipeline_A")
    # 指定了别的任务 id：不生效
    assert abort_mod.request_abort("pipeline_B") is False
    assert not abort_mod.is_aborted()
    # 匹配当前任务：生效
    assert abort_mod.request_abort("pipeline_A") is True
    assert abort_mod.is_aborted()
    abort_mod.end_pipeline()
    # 清理，避免影响其它测试
    abort_mod.begin_pipeline("pipeline_cleanup")
    abort_mod.end_pipeline()
