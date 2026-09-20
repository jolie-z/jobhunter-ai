#!/usr/bin/env python3
"""
策略数据库初始化与迁移脚本：
将 rule_config.json 的全部规则迁移到 SQLite job_strategies 表，
统一收敛为 keyword_rules 结构，废弃原始 JSON 配置文件。

用法：python init_strategy_db.py
"""
import os
import sys
import json
import sqlite3

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
DB_PATH = os.path.join(PROJECT_ROOT, "data", "job_hunter.db")
JSON_PATH = os.path.join(CURRENT_DIR, "rule_config.json")


def init_strategy_table(conn):
    """创建 job_strategies 表（如果不存在）。"""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_strategies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name TEXT NOT NULL,
            is_active INTEGER DEFAULT 0,
            min_salary_k INTEGER,
            max_salary_k INTEGER,
            experience_years_max INTEGER,
            exclude_education TEXT,
            allowed_cities TEXT,
            safe_phrases TEXT,
            keyword_rules TEXT,
            ai_scout_rules TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    print("✅ job_strategies 表创建成功（或已存在）。")


def migrate_json_to_db(conn):
    """读取 rule_config.json，转化并写入 job_strategies 表。"""
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    coarse = cfg.get("coarse_filter_rules", {})

    # ---------- 基础标量字段 ----------
    min_salary_k = coarse.get("min_salary_threshold_k", 10)
    max_salary_k = coarse.get("max_salary_threshold_k", 25)
    experience_years_max = coarse.get("experience_years_threshold", 7)
    exclude_education = json.dumps(coarse.get("reject_education", []), ensure_ascii=False)
    allowed_cities = json.dumps(cfg.get("allowed_cities", []), ensure_ascii=False)
    safe_phrases = json.dumps(cfg.get("safe_phrases", []), ensure_ascii=False)

    # ---------- 构建统一 keyword_rules ----------
    keyword_rules = []
    seen = set()  # (keyword_lower, scope, action) 去重

    def _add(keyword, scope, action, weight=0):
        key = (keyword.lower(), scope, action)
        if key not in seen:
            seen.add(key)
            keyword_rules.append({
                "keyword": keyword,
                "scope": scope,
                "action": action,
                "weight": weight,
            })

    # 1. reject_titles + title_veto_words → scope=title, action=reject
    for kw in coarse.get("reject_titles", []):
        _add(kw, "title", "reject")
    for kw in cfg.get("title_veto_words", []):
        _add(kw, "title", "reject")

    # 2. reject_experience → scope=experience, action=reject
    for kw in coarse.get("reject_experience", []):
        _add(kw, "experience", "reject")

    # 3. veto_keywords → scope=jd, action=reject
    for kw in cfg.get("veto_keywords", []):
        _add(kw, "jd", "reject")

    # 4. title_positive_words → scope=title, action=score
    for kw, w in cfg.get("title_positive_words", {}).items():
        _add(kw, "title", "score", w)

    # 5. title_negative_words → scope=title, action=score (weight 为负数)
    for kw, w in cfg.get("title_negative_words", {}).items():
        _add(kw, "title", "score", w)

    # 6. positive_keywords → scope=jd, action=score
    for kw, w in cfg.get("positive_keywords", {}).items():
        _add(kw, "jd", "score", w)

    # 7. negative_keywords → scope=jd, action=score (weight 为负数)
    for kw, w in cfg.get("negative_keywords", {}).items():
        _add(kw, "jd", "score", w)

    keyword_rules_json = json.dumps(keyword_rules, ensure_ascii=False)

    # ---------- 写入数据库 ----------
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO job_strategies
            (strategy_name, is_active, min_salary_k, max_salary_k,
             experience_years_max, exclude_education, allowed_cities,
             safe_phrases, keyword_rules)
        VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "默认AI大模型通用求职策略",
        min_salary_k, max_salary_k, experience_years_max,
        exclude_education, allowed_cities, safe_phrases, keyword_rules_json,
    ))
    conn.commit()

    # ---------- 打印迁移日志 ----------
    title_reject_cnt = sum(1 for r in keyword_rules if r["scope"] == "title" and r["action"] == "reject")
    jd_reject_cnt = sum(1 for r in keyword_rules if r["scope"] == "jd" and r["action"] == "reject")
    score_cnt = sum(1 for r in keyword_rules if r["action"] == "score")
    print(f"✅ 策略迁移成功！共导入 {len(keyword_rules)} 条去重后的关键词规则：")
    print(f"   🔸 标题一票否决词: {title_reject_cnt} 条")
    print(f"   🔸 JD 一票否决词:  {jd_reject_cnt} 条")
    print(f"   🔸 评分关键词:     {score_cnt} 条")
    print("   策略名称: 默认AI大模型通用求职策略")
    print(f"   薪资范围: {min_salary_k}K ~ {max_salary_k}K")
    print(f"   最高经验: {experience_years_max} 年")
    print(f"   允许城市: {json.loads(allowed_cities)}")


if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    try:
        init_strategy_table(conn)
        migrate_json_to_db(conn)
    finally:
        conn.close()
    print("🎉 迁移全部完成！rule_config.json 的规则已安全入库 job_strategies 表。")
