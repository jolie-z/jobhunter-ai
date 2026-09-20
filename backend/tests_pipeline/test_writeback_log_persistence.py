"""
回写日志落盘单测（2026-08-31）。

「接口回执成功、官网实际没生效」类问题只有拿到官网逐操作原话返回才能定位，
persist_writeback_log 把每次回写的完整 stdout/stderr、复核与写入明细存成日志文件。

覆盖（全部写入 tmp 目录，不碰真实 data/，不调任何接口）：
1. 正常载荷：文件生成、命名含平台、各分段齐全（message/脚本输出/复核/写入明细）
2. 失败载荷（data=None + stderr）：崩溃类日志保留 stderr 原文
3. 空输出：不抛异常，占位「(无输出)」
"""
import os

from app.api.resume_editor.common import persist_writeback_log


def _sample_data():
    return {
        "success": False,
        "message": "写入成功 52/56、失败 4 项；复核不一致 3 项",
        "data_source": {"using_snapshot": True, "stale": False},
        "verify": [
            {"module": "work_experience", "match": False, "note": "「电商副店长」字段内容与官网不一致"},
            {"module": "skill_tags", "match": True, "note": "11 条已生效"},
        ],
        "results": [
            {"module": "work_experience", "detail": "更新 某美妆集团", "ok": True, "resp_message": None},
            {"module": "education", "detail": "更新 某财经类大学", "ok": False, "resp_message": "官网拒绝原话示例"},
        ],
    }


def test_log_written_with_all_sections(tmp_path):
    path = persist_writeback_log(
        "zhilian", stdout="  [写入计划] work_experience 更新…\n  [✗] education …",
        stderr="", returncode=2, data=_sample_data(), dry_run=False, log_dir=str(tmp_path))
    assert os.path.exists(path)
    assert path.endswith("_zhilian.log")
    content = open(path, encoding="utf-8").read()
    assert "写入成功 52/56、失败 4 项" in content
    assert "脚本完整输出" in content and "[写入计划]" in content
    assert "复核明细" in content and "[✗] work_experience" in content and "[✓] skill_tags" in content
    assert "写入结果明细" in content and "[FAIL] education" in content and "官网拒绝原话示例" in content
    assert "数据源" in content and "退出码=2" in content


def test_log_keeps_stderr_for_crash_payload(tmp_path):
    path = persist_writeback_log(
        "51job", stdout="部分输出", stderr="Traceback: 官网拒绝的异常栈",
        returncode=1, data=None, dry_run=False, log_dir=str(tmp_path))
    content = open(path, encoding="utf-8").read()
    assert "stderr" in content and "Traceback: 官网拒绝的异常栈" in content


def test_log_empty_output_placeholder(tmp_path):
    path = persist_writeback_log("boss", stdout="", stderr="", returncode=0,
                                 data={"success": True}, dry_run=True, log_dir=str(tmp_path))
    content = open(path, encoding="utf-8").read()
    assert "(无输出)" in content and "dry_run=True" in content
