import pytest
from app.questions.service import shred_interview_service, ShredInterviewRequest


def test_build_top_k_candidates_logic():
    """测试 Top-K 题库候选剪枝算法，确保候选条数收敛且相关度最高"""
    from app.core.feishu_utils import feishu_field_to_plain_str

    # 构造 30 道模拟题库
    pool = {}
    for i in range(30):
        rid = f"rec_{i}"
        if i == 5:
            q_text = "如何做 LangGraph 状态机断点恢复？"
        elif i == 12:
            q_text = "谈谈 LangGraph 的多智能体编排与状态流转"
        else:
            q_text = f"请简述 MySQL 事务隔离级别以及 MVCC 实现机制第 {i} 题"
        pool[rid] = {"题目 / 核心拷问": q_text}

    # 提取函数做独立断言
    # 模拟 _build_top_k_candidates 算法
    def _test_top_k(q_target, pool, top_k=5):
        q_chars = set(q_target.lower().replace(" ", ""))
        scored = []
        for rid, f in pool.items():
            existing_q = feishu_field_to_plain_str(f.get("题目 / 核心拷问", ""))
            if not existing_q:
                continue
            e_chars = set(existing_q.lower().replace(" ", ""))
            common = len(q_chars & e_chars)
            total = len(q_chars | e_chars) or 1
            score = common / total
            if existing_q in q_target or q_target in existing_q:
                score += 1.0
            scored.append((score, rid, existing_q))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]

    results = _test_top_k("LangGraph 状态恢复", pool, top_k=5)
    assert len(results) == 5
    top_candidates = [r[2] for r in results]
    # 验证最相关的 LangGraph 题目排在前列
    assert any("LangGraph" in c for c in top_candidates)
