
from pydantic import BaseModel


class BatchTaskRequest(BaseModel):
    task_type: str
    job_ids: list[str]
    scheduled_at: str | None = None
