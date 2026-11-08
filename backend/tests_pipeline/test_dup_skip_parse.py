"""重复跳过行识别单测（dup_skip_parse.count_duplicate_skip）

样本取自四平台 collector 的真实 print 原文（boss_collector.py:355/398、51job_collector.py:253、
liepin_crawler.py:505、zhilian_collector.py:831/819），文案改动时本测试即红。
口径：只计「与库内已有岗位重复」；过期拦截/解析失败/普通行 = 0。
"""
from app.automation.dup_skip_parse import count_duplicate_skip


def test_boss_precheck_duplicate():
    line = "   ⏩ [拦截] [3/20] 字节跳动 - AI Agent工程师 | 数据库已存在，跳过！"
    assert count_duplicate_skip(line) == 1


def test_boss_insert_ignore_fallback():
    line = "   ⚠️ [数据已存在] 🏢 字节跳动 | AI Agent工程师 (链接已存在，跳过)"
    assert count_duplicate_skip(line) == 1


def test_51job_precheck_duplicate():
    line = "      ⏩ [跳过] 华为技术有限公司 - 后端开发 (已在库)"
    assert count_duplicate_skip(line) == 1


def test_liepin_precheck_duplicate():
    line = "   ⏩ [5/40] 跳过已收录: 腾讯科技 - 大模型算法"
    assert count_duplicate_skip(line) == 1


def test_zhilian_precheck_duplicate():
    line = "   ⏩ [拦截] [2/30] 阿里巴巴 - Agent开发 | 数据库已存在，跳过！"
    assert count_duplicate_skip(line) == 1


def test_zhilian_express_jump_whole_batch():
    line = "⏩ [极速跃迁] 第 4 批 (12/12 岗位均已在库，跳过详情解析)，加速滑动下一批..."
    assert count_duplicate_skip(line) == 12


def test_zhilian_express_jump_tolerates_whitespace():
    line = "⏩ [极速跃迁] 第 4 批 ( 7 / 7 岗位均已在库，跳过详情解析)，加速滑动下一批..."
    assert count_duplicate_skip(line) == 7


def test_non_duplicate_skips_counted_as_zero():
    # liepin 过期拦截（180 天陈旧，非重复）
    assert count_duplicate_skip("   ⏳ [过期拦截] 岗位已 200 天未刷新 (超过180天阈值)，跳过: XX - YY") == 0
    # zhilian 解析失败（非重复）
    assert count_duplicate_skip("   ⏩ [跳过] 无法获取职位信息。") == 0
    # 普通进度行
    assert count_duplicate_skip("   🔍 [3/20] 正在抓取详情: 字节跳动 - AI Agent工程师") == 0
    assert count_duplicate_skip("[入库成功] 已保存岗位: XX") == 0


def test_empty_and_garbage_lines():
    assert count_duplicate_skip("") == 0
    assert count_duplicate_skip(None) == 0  # type: ignore[arg-type]
    assert count_duplicate_skip("!!!乱码行!!!") == 0
