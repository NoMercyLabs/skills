"""Outgoing webhook delivery: payload signing and a bounded retry helper."""
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request

from app import config, db


def queue_event(conn, project_id, event, data):
    hooks = db.active_webhooks(conn, project_id)
    for hook in hooks:
        db.enqueue_job(
            conn,
            "webhook",
            {"hook_id": hook["id"], "event": event, "data": data},
        )
    return len(hooks)


def sign_body(secret, body):
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def with_retries(call, attempts, base_delay):
    """Run call() until it works or the caller's attempt budget is spent."""
    tries = 0
    while True:
        try:
            return call()
        except (urllib.error.URLError, TimeoutError):
            tries += 1
            if tries >= attempts:
                raise
            time.sleep(base_delay * (2 ** tries))


def post_once(url, body, signature):
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Task-Signature": signature,
        },
    )
    with urllib.request.urlopen(
        request, timeout=config.WEBHOOK_TIMEOUT_SECONDS
    ) as response:
        return response.status


def deliver(conn, payload):
    hook = db.fetch_one(
        conn, "SELECT * FROM webhooks WHERE id = ?", (payload["hook_id"],)
    )
    if hook is None or not hook["active"]:
        return False
    body = json.dumps(
        {"event": payload["event"], "data": payload["data"]},
        separators=(",", ":"),
    ).encode("utf-8")
    signature = sign_body(hook["secret"], body)
    status = with_retries(
        lambda: post_once(hook["url"], body, signature),
        config.WEBHOOK_MAX_ATTEMPTS,
        0.5,
    )
    return 200 <= status < 300
