import json
import os
import re
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "job_hunter.db")


def load_active_strategy():
    """从 SQLite 数据库实时拉取当前激活的策略模板"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT min_salary_k, max_salary_k, experience_years_max, "
            "exclude_education, allowed_cities, safe_phrases, keyword_rules "
            "FROM job_strategies WHERE is_active = 1 LIMIT 1"
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            print("⚠️ 未找到激活的求职策略，将使用空策略兜底")
            return None

        return {
            "min_salary_k": row[0],
            "max_salary_k": row[1],
            "experience_years_max": row[2],
            "exclude_education": json.loads(row[3] or "[]"),
            "allowed_cities": json.loads(row[4] or "[]"),
            "safe_phrases": json.loads(row[5] or "[]"),
            "keyword_rules": json.loads(row[6] or "[]"),
        }
    except Exception as e:
        print(f"❌ 读取策略数据库失败: {e}")
        return None


class StructuralFilterEngine:
    def __init__(self):
        self.strategy = load_active_strategy()
        if not self.strategy:
            self.strategy = {
                "min_salary_k": 10, "max_salary_k": 25, "experience_years_max": 7,
                "exclude_education": [], "allowed_cities": [],
                "safe_phrases": [], "keyword_rules": [],
            }

    def is_obvious_garbage(self, job_title, experience_req, education_req) -> tuple[bool, str]:
        """
        判断是否为明显的垃圾岗位
        返回: (是否是垃圾岗位, 淘汰原因)
        """
        title = str(job_title).lower() if job_title else ""
        exp = str(experience_req) if experience_req else ""
        edu = str(education_req) if education_req else ""

        # 1. 统一 keyword_rules 循环（标题 & 经验粗筛）
        for rule in self.strategy.get("keyword_rules", []):
            kw = rule["keyword"]
            scope = rule["scope"]
            action = rule["action"]
            kw_lower = kw.lower()

            if action == "reject":
                if scope == "title" and kw_lower in title:
                    return True, f"标题包含排除词: {kw}"
                elif scope == "experience" and kw_lower in exp.lower():
                    return True, f"经验要求不符: {kw}"

        # 2. 学历粗筛（从策略的 exclude_education 列表）
        for edu_word in self.strategy.get("exclude_education", []):
            if edu_word in edu:
                return True, f"学历要求不符: {edu_word}"

        return False, ""
