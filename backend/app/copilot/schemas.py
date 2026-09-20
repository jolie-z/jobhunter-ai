from typing import Any, Literal

from pydantic import BaseModel


class CopilotChatRequest(BaseModel):
    context: dict[str, Any] = {}
    section_title: str | None = "全局问答"
    history: list[dict[str, Any]] = []
    user_question: str

class VoiceCopilotChatRequest(BaseModel):
    section_title: str = ""
    original_text: str = ""
    job_description: str = ""
    evaluation_report: str = ""
    history: list[dict[str, Any]] = []

class InterviewRequest(BaseModel):
    job_id: str
    company: str
    job_group: str
    business_track: str | None = None
    jd_text: str | None = None
    cached_intel: str | None = None
    cached_qa: str | None = None
    cached_rq: str | None = None
    force_refresh: bool = False
    resume_text: str | None = None
    evaluation_report: str | None = None
    refresh_target: Literal['all', 'company', 'summary', 'qa'] = 'all'

class CheckIntelRequest(BaseModel):
    job_group: str
    business_track: str | None = None
    current_count: int = 0
