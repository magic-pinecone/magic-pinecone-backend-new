from celery import Celery
from app.core.config import settings

celery_app = Celery(
    'magic_pinecone',
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_BACKEND,
)

celery_app.conf.update(
    # Timezone
    timezone='Asia/Taipei',
    enable_utc=True,
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],

    # Mission Tracking
    task_track_started=True,
    result_expires=86400,

    # Worker optimization
    worker_prefetch_multiplier=1,
    task_soft_time_limit=600,
    task_time_limit=660,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

celery_app.autodiscover_tasks(['app.task.scraper_tasks'])