from datetime import timedelta

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "magic_pinecone",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.course_scraper"],
)

celery_app.conf.update(
    imports=["app.tasks.course_scraper"],
    # Timezone
    timezone="Asia/Taipei",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Mission Tracking
    task_track_started=True,
    result_expires=86400,
    # Worker optimization
    worker_prefetch_multiplier=1,
    task_soft_time_limit=600,
    task_time_limit=660,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Periodic Scheduled Tasks (Celery Beat)
    beat_schedule={
        "scrape-ncu-courses-periodic": {
            "task": "tasks.course_scraper.scrape_ncu_courses",
            "schedule": timedelta(minutes=settings.SCRAPER_INTERVAL_MINUTES),
        },
    },
)

celery_app.autodiscover_tasks(["app.tasks.course_scraper"])
