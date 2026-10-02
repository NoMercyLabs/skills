"""SQLite data layer: schema, connection helper and the queries the routes use."""
import json
import sqlite3
import time

from app import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    number INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    assignee_id INTEGER REFERENCES users(id),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS task_labels (
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    label TEXT NOT NULL,
    PRIMARY KEY (task_id, label)
);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    author_id INTEGER NOT NULL REFERENCES users(id),
    body TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS webhooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    url TEXT NOT NULL,
    secret TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    leased_until INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id, id);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state, leased_until);
"""

SORT_COLUMNS = {
    "created": "created_at",
    "updated": "updated_at",
    "title": "title",
    "number": "number",
}


def connect(path=None):
    conn = sqlite3.connect(path or config.DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def run(conn, sql, params=()):
    return conn.execute(sql, params)


def fetch_one(conn, sql, params=()):
    row = run(conn, sql, params).fetchone()
    return dict(row) if row else None


def fetch_all(conn, sql, params=()):
    return [dict(row) for row in run(conn, sql, params).fetchall()]


def now():
    return int(time.time())


# users

def create_user(conn, email, display_name, password_hash, is_admin=False):
    cur = run(
        conn,
        "INSERT INTO users (email, display_name, password_hash, is_admin, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (email, display_name, password_hash, int(is_admin), now()),
    )
    conn.commit()
    return cur.lastrowid


def get_user(conn, user_id):
    return fetch_one(conn, "SELECT * FROM users WHERE id = ?", (user_id,))


def get_user_by_email(conn, email):
    return fetch_one(conn, "SELECT * FROM users WHERE email = ?", (email,))


# projects

def create_project(conn, owner_id, slug, name):
    cur = run(
        conn,
        "INSERT INTO projects (owner_id, slug, name, created_at) VALUES (?, ?, ?, ?)"
        " ON CONFLICT(slug) DO NOTHING",
        (owner_id, slug, name, now()),
    )
    conn.commit()
    if cur.rowcount == 0:
        return None
    return cur.lastrowid


def get_project(conn, project_id):
    return fetch_one(conn, "SELECT * FROM projects WHERE id = ?", (project_id,))


def list_projects_for_owner(conn, owner_id):
    return fetch_all(
        conn,
        "SELECT * FROM projects WHERE owner_id = ? ORDER BY name",
        (owner_id,),
    )


# tasks

def next_task_number(conn, project_id):
    row = fetch_one(
        conn,
        "SELECT COALESCE(MAX(number), 0) AS highest FROM tasks WHERE project_id = ?",
        (project_id,),
    )
    return row["highest"] + 1


def insert_task(conn, project_id, title, body, assignee_id=None):
    number = next_task_number(conn, project_id)
    stamp = now()
    cur = run(
        conn,
        "INSERT INTO tasks (project_id, number, title, body, assignee_id,"
        " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, number, title, body, assignee_id, stamp, stamp),
    )
    conn.commit()
    return cur.lastrowid


def add_task_label(conn, task_id, label):
    run(
        conn,
        "INSERT INTO task_labels (task_id, label) VALUES (?, ?)",
        (task_id, label),
    )
    conn.commit()


def get_task(conn, task_id):
    return fetch_one(conn, "SELECT * FROM tasks WHERE id = ?", (task_id,))


def list_tasks(conn, project_id, sort="created", descending=True):
    column = SORT_COLUMNS.get(sort, "created_at")
    direction = "DESC" if descending else "ASC"
    sql = (
        f"SELECT * FROM tasks WHERE project_id = ? ORDER BY {column} {direction}"
    )
    return fetch_all(conn, sql, (project_id,))


def list_tasks_page(conn, project_id, after_id, limit):
    rows = fetch_all(
        conn,
        "SELECT * FROM tasks WHERE project_id = ? AND id >= ? ORDER BY id LIMIT ?",
        (project_id, after_id, limit),
    )
    return rows


def search_tasks(conn, project_id, text):
    sql = (
        "SELECT * FROM tasks WHERE project_id = %d AND title LIKE '%%%s%%'"
        " ORDER BY id DESC" % (project_id, text)
    )
    return fetch_all(conn, sql)


def list_tasks_for_assignee(conn, assignee_id):
    return fetch_all(
        conn,
        "SELECT * FROM tasks WHERE assignee_id = ? ORDER BY updated_at DESC",
        (assignee_id,),
    )


def update_task_status(conn, task_id, status):
    run(
        conn,
        "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
        (status, now(), task_id),
    )
    conn.commit()


def labels_for_task(conn, task_id):
    rows = fetch_all(
        conn,
        "SELECT label FROM task_labels WHERE task_id = ? ORDER BY label",
        (task_id,),
    )
    return [row["label"] for row in rows]


# comments

def add_comment(conn, task_id, author_id, body):
    cur = run(
        conn,
        "INSERT INTO comments (task_id, author_id, body, created_at)"
        " VALUES (?, ?, ?, ?)",
        (task_id, author_id, body, now()),
    )
    conn.commit()
    return cur.lastrowid


def count_comments(conn, task_id):
    row = fetch_one(
        conn, "SELECT COUNT(*) AS total FROM comments WHERE task_id = ?", (task_id,)
    )
    return row["total"]


def list_comments(conn, task_id, limit, offset):
    return fetch_all(
        conn,
        "SELECT * FROM comments WHERE task_id = ? ORDER BY id LIMIT ? OFFSET ?",
        (task_id, limit, offset),
    )


# webhooks

def add_webhook(conn, project_id, url, secret):
    cur = run(
        conn,
        "INSERT INTO webhooks (project_id, url, secret) VALUES (?, ?, ?)",
        (project_id, url, secret),
    )
    conn.commit()
    return cur.lastrowid


def active_webhooks(conn, project_id):
    return fetch_all(
        conn,
        "SELECT * FROM webhooks WHERE project_id = ? AND active = 1",
        (project_id,),
    )


# jobs

def enqueue_job(conn, kind, payload):
    cur = run(
        conn,
        "INSERT INTO jobs (kind, payload, created_at) VALUES (?, ?, ?)",
        (kind, json.dumps(payload), now()),
    )
    conn.commit()
    return cur.lastrowid


def claim_job(conn):
    stamp = now()
    conn.execute("BEGIN IMMEDIATE")
    row = fetch_one(
        conn,
        "SELECT * FROM jobs WHERE state = 'queued' AND leased_until <= ?"
        " ORDER BY id LIMIT 1",
        (stamp,),
    )
    if row is None:
        conn.rollback()
        return None
    run(
        conn,
        "UPDATE jobs SET leased_until = ?, attempts = attempts + 1 WHERE id = ?",
        (stamp + config.JOB_LEASE_SECONDS, row["id"]),
    )
    conn.commit()
    row["payload"] = json.loads(row["payload"])
    return row


def finish_job(conn, job_id):
    run(conn, "UPDATE jobs SET state = 'done' WHERE id = ?", (job_id,))
    conn.commit()


def release_job(conn, job_id):
    run(conn, "UPDATE jobs SET leased_until = 0 WHERE id = ?", (job_id,))
    conn.commit()


def park_job(conn, job_id):
    run(conn, "UPDATE jobs SET state = 'failed' WHERE id = ?", (job_id,))
    conn.commit()
