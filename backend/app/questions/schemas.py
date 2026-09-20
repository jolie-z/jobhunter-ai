
from pydantic import BaseModel


class UpdateQuestionRequest(BaseModel):
    mastery_status: str | None = None
    golden_answer: str | None = None
    ai_demo: str | None = None

class AddResumeQACardRequest(BaseModel):
    job_id: str
    question: str
    answer: str

class ShredInterviewRequest(BaseModel):
    job_id: str
    record_text: str
