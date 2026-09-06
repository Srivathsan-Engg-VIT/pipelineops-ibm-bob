from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from render_queue.logging_config import get_logger

if TYPE_CHECKING:
    from render_queue.models import RenderJob

logger = get_logger(__name__)


class AlertNotifier(Protocol):
    def notify(self, job: RenderJob) -> None: ...


class LogAlertNotifier:
    def notify(self, job: RenderJob) -> None:
        logger.critical(
            "job_failed_alert",
            shot=job.shot,
            retry_count=job.retry_count,
            error=job.error,
        )
