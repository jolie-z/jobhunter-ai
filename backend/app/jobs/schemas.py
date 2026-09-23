from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class JobRecord(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    record_id: Any | None = None
    job_name: str | None = None
    company_name: str | None = None
    city: str | None = None
    salary: str | None = None
    follow_status: str | None = None
    scale: str | None = None
    industry: str | None = None
    education: str | None = None
    experience: str | None = None
    job_detail: str | None = None
    hr_skills: list[str] | None = None
    benefits: list[str] | None = None
    hr_active: str | None = None
    delivery_date: str | None = None
    fetch_time: str | None = None
    work_address: str | None = None
    manual_refined_resume: str | None = None
    my_review: str | None = None
    ai_rewrite_json: str | None = None
    dream_picture: str | None = None
    ats_ability_analysis: str | None = None
    strong_fit_assessment: str | None = None
    risk_red_flags: str | None = None
    deep_action_plan: str | None = None
    greeting_msg: str | None = None
    platform: str | None = None
    role: str | None = None
    publish_date: str | None = None
    second_qa_report: str | None = None
    grade: str | None = None
    role_match: float | None = None
    skills_align: float | None = None
    seniority: float | None = None
    compensation: float | None = None
    interview_prob: float | None = None
    company_stage: float | None = None
    market_fit: float | None = None
    growth: float | None = None
    ai_evaluation_detail: str | None = None
    job_link: str | None = None
    amap_link: str | None = None
    company_ai_intel: str | None = Field(default=None, alias="公司业务情报")
    predicted_qa: str | None = Field(default=None, alias="专属面试预测")
    live_interview_record: str | None = Field(default=None, alias="现场面试记录")
    resume_qa: str | None = Field(default=None, alias="简历专项QA")
    interview_prep_report: str | None = None

class JobsResponse(BaseModel):
    items: list[JobRecord]
    status: str


# ==================== 以下 Schema 迁移自 OLD_main_7000.py ====================

class SettingsPayload(BaseModel):
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str | None = None
    FEISHU_APP_ID: str | None = None
    FEISHU_APP_SECRET: str | None = None
    FEISHU_APP_TOKEN: str | None = None


class JobImportTextRequest(BaseModel):
    raw_text: str


class JobImportImageRequest(BaseModel):
    images_base64: list[str]


class JobImportParseRequest(BaseModel):
    """极速录入第一步：图文可同时提供，后端并行解析合并，不落库。"""
    raw_text: str = ""
    images_base64: list[str] = []


class JobImportConfirmRequest(BaseModel):
    """极速录入第二步：确认落库。查重命中时需 force_duplicate=true 才放行。"""
    fields: dict[str, Any]
    force_duplicate: bool = False


class UpdateScheduleRequest(BaseModel):
    job_id: str
    interview_time: str
    interview_location: str
    follow_status: str | None = "一面"
    resume_qa: str | None = None

class SaveLiveFieldsRequest(BaseModel):
    job_id: str
    live_record: str | None = None
    resume_qa: str | None = None


class SaveTranscriptRequest(BaseModel):
    job_id: str
    transcript: str
    is_overwrite: bool = False
    generate_report: bool = False
    jd_text: str = ""
    role: str = "business"
    style: str = "coach"




class ChatCommandRequest(BaseModel):
    command: str
    task_id: str | None = None


class GeneratePDFRequest(BaseModel):
    job_id: str

class AIPolishRequest(BaseModel):
    selected_text: str
    instruction: str

class UpdateJobStatusRequest(BaseModel):
    job_id: str
    status: str
    platform: str = "BOSS直聘"

class UpdateReviewCommentsRequest(BaseModel):
    job_id: str
    comments: str

class UpdateGreetingRequest(BaseModel):
    job_id: str
    greeting: str

class BatchDeleteRequest(BaseModel):
    job_ids: list[str]

class CheckAiArtifactsRequest(BaseModel):
    record_ids: list[str] = Field(min_length=1, description="岗位记录 ID 列表（兼容「平台-recXXX」复合 ID）")

class QAEvaluateRequest(BaseModel):
    job_id: str
    job_description: str
    resume_text: str
    platform: str = "BOSS直聘"

class SaveManualResumeRequest(BaseModel):
    job_id: str
    resume_text: str
    structured_json: dict[str, Any] | None = None
    platform: str = "BOSS直聘"
    current_status: str | None = None  # 支持前端透传当前状态，避免额外查表

class CopilotChatRequest(BaseModel):
    user_question: str
    context: dict[str, Any]
    history: list[dict[str, str]]
    section_title: str | None = "全局问答"

class VoiceCopilotChatRequest(BaseModel):
    job_description: str
    section_title: str
    original_text: str
    history: list[dict[str, str]]
    evaluation_report: str = ""

class InterviewPrepRequest(BaseModel):
    job_id: str
    resume_text: str
    job_description: str
    company_name: str

class JobResumePdfRequest(BaseModel):
    job_id: str
    resume_data_v2: dict[str, Any]
    page_size: str = "A4"
    # 简历模版皮肤：classic=普通(黑白) / color=彩色
    template: str = "classic"
