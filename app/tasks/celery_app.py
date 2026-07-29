from celery import Celery
from app.core.config import settings

# Create Celery App instance
celery_app = Celery(
    "lead_gen_scraper",
    broker=settings.REDIS_URL_FORMATTED,
    backend=settings.REDIS_URL_FORMATTED
)

is_ssl = settings.REDIS_URL_FORMATTED.startswith("rediss://")

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_use_ssl={'ssl_cert_reqs': 'none'} if is_ssl else False,
    redis_backend_use_ssl={'ssl_cert_reqs': 'none'} if is_ssl else False,
    task_track_started=True,
    imports=[
        "app.tasks.test_tasks",
        "app.tasks.scrape_tasks",
    ]
)
