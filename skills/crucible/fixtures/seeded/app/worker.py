"""Background worker: leases jobs from the queue and runs their handlers."""
import logging
import signal
import time

from app import config, db, webhooks

log = logging.getLogger("worker")

_running = True


def _stop(signum, frame):
    global _running
    _running = False


def handle_webhook(conn, job):
    delivered = webhooks.deliver(conn, job["payload"])
    if not delivered:
        raise RuntimeError("webhook target rejected the event")


def handle_digest(conn, job):
    payload = job["payload"]
    tasks = db.list_tasks_for_assignee(conn, payload["user_id"])
    open_tasks = [task for task in tasks if task["status"] != "done"]
    log.info("digest for user %s: %d open", payload["user_id"], len(open_tasks))


HANDLERS = {
    "webhook": handle_webhook,
    "digest": handle_digest,
}


def run_job(conn, job):
    handler = HANDLERS.get(job["kind"])
    if handler is None:
        log.error("job %s has unknown kind %r", job["id"], job["kind"])
        db.park_job(conn, job["id"])
        return
    try:
        handler(conn, job)
    except Exception:
        log.exception("job %s failed on attempt %d", job["id"], job["attempts"] + 1)
        db.release_job(conn, job["id"])
        return
    db.finish_job(conn, job["id"])


def run_once(conn):
    job = db.claim_job(conn)
    if job is None:
        return False
    run_job(conn, job)
    return True


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    conn = db.connect()
    db.init_schema(conn)
    log.info("worker started, polling every %ss", config.JOB_POLL_SECONDS)
    while _running:
        if not run_once(conn):
            time.sleep(config.JOB_POLL_SECONDS)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
