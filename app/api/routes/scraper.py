from datetime import timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.celery_app import celery_app
from app.core.config import settings
from app.tasks.course_scraper import scrape_ncu_courses

router = APIRouter(prefix="/scraper", tags=["scraper"])


class ScheduleUpdateRequest(BaseModel):
    interval_minutes: int = Field(
        ..., ge=1, le=43200, description="Crawling interval in minutes"
    )


@router.post("/trigger", response_model=dict[str, Any])
def trigger_scraper() -> Any:
    """Manually trigger NCU course scraping task in background Celery worker."""
    task = scrape_ncu_courses.delay(save_to_db=True)
    return {
        "message": "Scraper task triggered successfully",
        "task_id": task.id,
        "status": task.status,
    }


@router.get("/status/{task_id}", response_model=dict[str, Any])
def get_scraper_task_status(task_id: str) -> Any:
    """Check status and progress of a Celery scraper task."""
    result = celery_app.AsyncResult(task_id)
    response = {
        "task_id": task_id,
        "status": result.status,
        "result": None,
    }

    if result.status == "PROGRESS":
        response["result"] = result.info
    elif result.ready():
        if result.successful():
            response["result"] = result.result
        else:
            response["result"] = str(result.info)

    return response


@router.get("/schedule", response_model=dict[str, Any])
def get_scraper_schedule() -> Any:
    """Get current Celery Beat scraper periodic schedule."""
    schedule_conf = celery_app.conf.beat_schedule.get("scrape-ncu-courses-periodic", {})
    sched = schedule_conf.get("schedule")

    minutes = settings.SCRAPER_INTERVAL_MINUTES
    if isinstance(sched, timedelta):
        minutes = int(sched.total_seconds() // 60)

    return {
        "task_name": "scrape-ncu-courses-periodic",
        "interval_minutes": minutes,
        "target_task": schedule_conf.get("task"),
    }


@router.post("/schedule", response_model=dict[str, Any])
def update_scraper_schedule(body: ScheduleUpdateRequest) -> Any:
    """Dynamically update Celery Beat scraper frequency."""
    new_minutes = body.interval_minutes

    # Update in-memory runtime settings and Celery Beat configuration
    settings.SCRAPER_INTERVAL_MINUTES = new_minutes
    celery_app.conf.beat_schedule["scrape-ncu-courses-periodic"] = {
        "task": "tasks.course_scraper.scrape_ncu_courses",
        "schedule": timedelta(minutes=new_minutes),
    }

    return {
        "message": f"Scraper schedule updated to every {new_minutes} minutes",
        "interval_minutes": new_minutes,
    }
