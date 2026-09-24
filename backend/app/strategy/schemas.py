from typing import Any

from pydantic import BaseModel


class ActiveStrategyResponse(BaseModel):
    min_salary_k: int
    max_salary_k: int
    experience_years_max: int
    exclude_education: list[str]
    allowed_cities: list[str]
    safe_phrases: list[str]
    keyword_rules: list[Any]
    ai_scout_rules: list[Any] = []

class SaveConfigRequest(BaseModel):
    table_type: str  # "resume"
    record_id: str | None = None
    fields: dict[str, Any]
    # 原文快照 ID（= 上传 task_id）：保存时写飞书快照字段并记录修正回流；老简历/本地草稿无此值
    snapshot_id: str | None = None

class ToggleResumeStatusRequest(BaseModel):
    record_id: str

class ActivateResumeRequest(BaseModel):
    record_id: str

class DeleteStrategyRequest(BaseModel):
    table_type: str  # "resume"
    record_id: str

class UpdateStrategyRequest(BaseModel):
    min_salary_k: int = 10
    max_salary_k: int = 25
    experience_years_max: int = 7
    exclude_education: list[str] = []
    allowed_cities: list[str] = []
    safe_phrases: list[str] = []
    keyword_rules: list[str] = []
    ai_scout_rules: list[Any] = []

class PreferenceUpsertRequest(BaseModel):
    record_id: str | None = None
    type: str
    rule: str
    status: str

class WeightsUpdateRequest(BaseModel):
    weights: dict[str, float]

class ChatMessage(BaseModel):
    role: str
    content: str

class GrillExperienceRequest(BaseModel):
    original_experience: str
    chat_history: list[ChatMessage]
    current_turn: int
    jd_report_context: str | None = None
    full_resume_context: str | None = None

class SyncBasicModuleRequest(BaseModel):
    module_title: str
    current_content: str
    experiences_context: str

class AtsAlignRequest(BaseModel):
    original_experience: str
    jd_report_context: str
    full_resume_context: str | None = None

class GlobalDiagnosisRequest(BaseModel):
    jd_text: str
    full_resume_context: str

class GrillSuggestionRequest(BaseModel):
    jd_text: str
    full_resume_context: str

class ResetResumeRequest(BaseModel):
    job_id: str
class ProjectItem(BaseModel):
    id: str
    title: str
    content: str
    category: str | None = None  # "工作经历" | "项目经历"，用于让 LLM 区分使用 STAR 还是 CRD 格式

class FilterProjectsRequest(BaseModel):
    jd_text: str
    diagnosis_report: str
    projects: list[ProjectItem]

class CompressWorkRequest(BaseModel):
    jd_text: str
    diagnosis_report: str
    work_experiences: list[ProjectItem]

class InitialDraftRequest(BaseModel):
    jd_text: str
    diagnosis_report: str
    experiences: list[ProjectItem]
    full_resume_context: str | None = None  # 🌟 初版改写注入全量视野约束

class ResumePdfRequest(BaseModel):
    record_id: str
    page_size: str = "A4"
    source: str | None = None
    company: str | None = None
    job_title: str | None = None
    # 简历模版皮肤：classic=普通(黑白) / color=彩色；由打印页路由到对应组件
    template: str = "classic"

class FormatMarkdownRequest(BaseModel):
    module_title: str
    current_content: str

class PreviewPdfDirectRequest(BaseModel):
    resume_data: dict[str, Any]
    page_size: str = "A4"
    template: str = "classic"

class PredictDescRequest(BaseModel):
    keyword: str
