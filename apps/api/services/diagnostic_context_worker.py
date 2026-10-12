"""Prepare persisted diagnostic snapshots without model calls or price writes."""
import logging
from threading import Event, Thread

from apps.api.db.session import get_session_factory
from apps.api.services.hermes_diagnostic_service import prepare_hermes_context

logger = logging.getLogger(__name__)


def process_context_batch(*, limit: int = 20, stop: Event | None = None) -> int:
    count = 0
    for _ in range(max(1, min(limit, 200))):
        if stop is not None and stop.is_set():
            break
        with get_session_factory()() as db:
            record = prepare_hermes_context(db)
        if record is None:
            break
        count += 1
    return count


def start_context_worker() -> tuple[Event, Thread]:
    stop = Event()

    def run():
        while not stop.is_set():
            try:
                process_context_batch(stop=stop)
            except Exception:
                logger.exception("Diagnostic context worker could not process queue")
            stop.wait(2)

    thread = Thread(target=run, name="quote-diagnostic-context", daemon=True)
    thread.start()
    return stop, thread
