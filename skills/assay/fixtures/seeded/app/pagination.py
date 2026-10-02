"""Helpers that shape list responses into pages."""
import math

from app import db


def offset_page(total, page, per_page):
    pages = max(1, math.ceil(total / per_page))
    page = min(max(page, 1), pages)
    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": pages,
        "offset": (page - 1) * per_page,
    }


def comment_page(conn, task_id, page, per_page):
    total = db.count_comments(conn, task_id)
    meta = offset_page(total, page, per_page)
    items = db.list_comments(conn, task_id, per_page, meta["offset"])
    return {"items": items, "meta": meta}


def cursor_page(conn, project_id, after_id, per_page):
    rows = db.list_tasks_page(conn, project_id, after_id, per_page + 1)
    has_more = len(rows) > per_page
    items = rows[:per_page]
    next_cursor = items[-1]["id"] if has_more else None
    return {"items": items, "next_cursor": next_cursor}
