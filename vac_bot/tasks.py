import os

from celery import Celery

from db import get_default_tenant_id
from vac_bot.curator import run_change_detection


BROKER_URL = os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL", "redis://redis:6379/0"))
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", os.getenv("REDIS_URL", "redis://redis:6379/0"))

celery_app = Celery(
    "general_bot",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=["vac_bot.tasks"],
)

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "nightly-change-detection": {
            "task": "vac_bot.tasks.run_change_detection_task",
            "schedule": 60 * 60 * 24,
            "args": (),
        },
    },
)


@celery_app.task(name="vac_bot.tasks.run_change_detection_task")
def run_change_detection_task(tenant_id=None):
    return run_change_detection(tenant_id=tenant_id or get_default_tenant_id())
