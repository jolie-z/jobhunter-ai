import json
import os
import re
import sqlite3

from app.core.db_paths import job_hunter_db_path

DB_PATH = job_hunter_db_path(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "job_hunter.db"))


def load_active_strategy():
    """从 SQLite 数据库实时拉取当前激活的策略模板"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        from app.strategy.strategy_row import STRATEGY_COLUMNS, map_strategy_row
        cursor.execute(
            f"SELECT {', '.join(STRATEGY_COLUMNS)} "
            "FROM job_strategies WHERE is_active = 1 LIMIT 1"
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            print("⚠️ 未找到激活的求职策略，将使用空策略兜底")
            return None

        return map_strategy_row(row)
    except Exception as e:
        if "no such table" in str(e):
            # 表缺失两种可能：全新机器首启建表引导尚未跑完（正常时序），或运行期库结构
            # 意外损坏/被删（需排查）。文案保持中立、不预设场景（agy P2 复审建议采纳）
            print(f"⏳ 策略数据表不存在（{e}），本次降级用空策略兜底；若非首次启动，请排查主库结构")
            return None
        print(f"❌ 读取策略数据库失败: {e}")
        return None


class StructuralFilterEngine:
    def __init__(self):
        self.strategy = load_active_strategy()
        if not self.strategy:
            self.strategy = {
                "min_salary_k": 10, "max_salary_k": 25, "experience_years_max": 7,
                "exclude_education": [], "require_education": [], "allowed_cities": [],
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

        # 2. 学历粗筛（从策略的 exclude_education 黑名单 / require_education 白名单，
        # 2026-11-02 审计 P1-9 全链路接入：两名单由写入侧互斥校验保证不同时配置）
        for edu_word in self.strategy.get("exclude_education", []):
            if edu_word in edu:
                return True, f"学历要求不符: {edu_word}"

        # 白名单语义（Opus plan-review P2 采纳）：仅对岗位 JD 解析出的具体学历值生效——
        # 「学历不限」/空串/未解析出任何已知档位时一律放行，防止误杀海量不限学历岗位。
        # 岗位值可能是组合串（"本科及以上"），按子串包含判定任一档位命中即通过
        require_list = self.strategy.get("require_education", [])
        if require_list:
            edu_stripped = edu.strip()
            is_unrestricted = (not edu_stripped) or ("不限" in edu_stripped) or ("无" == edu_stripped)
            if not is_unrestricted:
                matched_any = any(req in edu_stripped for req in require_list)
                # 学历阶梯（低→高）：白名单语义=最低门槛（CR-B2-R1-P2 采纳后定版）——
                # 岗位档位 ≥ 白名单最低档即放行；未识别档位（解析失败/非常规表述）
                # 一律放行（防误杀，与 schemas.py 注释"解析失败一律放行"一致）
                _EDU_LADDER = ("初中", "高中", "中专", "大专", "本科", "硕士", "博士")
                job_rank = next((i for i, lv in enumerate(_EDU_LADDER) if lv in edu_stripped), -1)
                min_rank = min((i for req in require_list for i, lv in enumerate(_EDU_LADDER) if lv in req), default=-1)
                # 岗位档位未识别（job_rank==-1）视为解析失败 → 放行；识别出的档位
                # 高于等于门槛（job_rank >= min_rank）放行；仅「识别出且低于门槛」淘汰。
                # min_rank==-1（白名单全为未识别词）→ 门槛无法建立，保守放行（CR-B2-R2-P2）
                if matched_any or job_rank < 0 or min_rank < 0 or job_rank >= min_rank:
                    pass  # 放行（含弹性向上：岗位档位高于门槛）
                else:
                    # 未命中任何白名单档位且无"以上/及以上"弹性措辞才淘汰：
                    # "大专及以上"命中白名单"大专"（子串）；"本科及以上"对白名单"大专"
                    # 也放行（岗位学历高于门槛，弹性向上，防误杀）
                    return True, f"学历白名单不符（要求: {'/'.join(require_list)}，岗位: {edu_stripped[:20]}）"

        return False, ""
