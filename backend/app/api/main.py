from fastapi import APIRouter

from app.api.routes import utils

api_router = APIRouter()
api_router.include_router(utils.router)


from app.jobs.router import router as jobs_router  # noqa: E402

api_router.include_router(jobs_router, prefix="/jobs", tags=["jobs"])

from app.tasks.router import router as tasks_router  # noqa: E402

api_router.include_router(tasks_router, prefix="/tasks", tags=["tasks"])

# Include Skills API (already has its own prefix in skills.py)
from app.api.routes.skills import router as skills_router  # noqa: E402

api_router.include_router(skills_router)
