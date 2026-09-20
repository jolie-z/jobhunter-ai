from fastapi import APIRouter

router = APIRouter(
    prefix="/job-hunter",
    tags=["job_hunter"]
)

@router.get("/ping")
async def ping():
    return {"message": "pong"}
