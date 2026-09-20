from pydantic import BaseModel


class GeneratePDFRequest(BaseModel):
    job_id: str
