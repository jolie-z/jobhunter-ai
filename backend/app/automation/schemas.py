from typing import Any

from pydantic import BaseModel


class AutopilotConfigSchema(BaseModel):
    cron_time: str = "09:00"
    auto_deliver_grades: list[str] = ["C", "D", "F"]
    auto_deliver_platforms: list[str] = ["boss", "liepin", "51job", "zhilian"]
    is_enabled: bool = True
    batch_limit: int = 20
    mass_apply_resume_id: str = ""  # 海投简历（C-F 级投递用）：简历库记录 ID，空=回退启用简历
    rewrite_base_resume_id: str = ""  # A/B 级改写底稿：指定后评估与改写都用它，空=用启用简历
    mass_apply_max_headcount: int = 1000  # 海投门槛：公司规模下限 ≥ 该值不海投，停在「已完成初步评估」
    mass_apply_greeting: str = ""  # 海投打招呼语：非空时 C-F 海投直接复用，空=每岗现场生成
    greeting_platforms: dict[str, bool] = {  # 指挥页「打招呼语·生成平台」开关
        "boss": True, "liepin": True, "51job": False, "zhilian": False,
    }
    platform_configs: dict[str, Any] = {
        "boss": {"limit": 0, "keyword": "", "city": "全国", "salary": "不限"},
        "xiaohongshu": {"limit": 0, "keyword": "", "sort_by": "general"},
        "liepin": {"limit": 0, "keyword": "", "city": "全国", "salary": "不限"},
        "zhilian": {"limit": 0, "keyword": "", "city": "全国", "salary": "不限"},
        "51job": {"limit": 0, "keyword": "", "city": "全国", "salary": "不限"}
    }

class AutopilotLogSchema(BaseModel):
    task_id: str
    started_at: str
    finished_at: str | None = None
    status: str
    jobs_processed: int = 0
    details: str = ""
