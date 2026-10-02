"""Route handlers. Each handler takes a Request and returns (status, body)."""
import mimetypes
import os
import secrets

from app import auth, config, db, pagination, validation, webhooks


class HttpError(Exception):
    def __init__(self, status, message, detail=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.detail = detail


def require_user(req):
    if req.user is None:
        raise HttpError(401, "authentication required")
    return req.user


def require_project_owner(req, project_id):
    user = require_user(req)
    project = db.get_project(req.conn, project_id)
    if project is None:
        raise HttpError(404, "project not found")
    if project["owner_id"] != user["sub"] and not user["adm"]:
        raise HttpError(403, "not your project")
    return project


def load_task(req, task_id):
    task = db.get_task(req.conn, task_id)
    if task is None:
        raise HttpError(404, "task not found")
    require_project_owner(req, task["project_id"])
    return task


def public_user(user):
    return {
        "id": user["id"],
        "email": user["email"],
        "display_name": user["display_name"],
        "is_admin": bool(user["is_admin"]),
    }


def public_task(conn, task):
    shaped = dict(task)
    shaped["labels"] = db.labels_for_task(conn, task["id"])
    return shaped


# accounts

def register(req):
    data = req.json()
    email = validation.require_email(data)
    name = validation.require_text(data, "display_name", maximum=80)
    password = validation.require_password(data)
    if db.get_user_by_email(req.conn, email):
        raise HttpError(409, "email already registered")
    user_id = db.create_user(
        req.conn, email, name, auth.hash_password(password)
    )
    return 201, {"id": user_id}


def login(req):
    data = req.json()
    email = validation.require_email(data)
    password = validation.require_password(data)
    user = db.get_user_by_email(req.conn, email)
    if user is None or not auth.check_password(password, user["password_hash"]):
        raise HttpError(401, "wrong email or password")
    token = auth.issue_token(user["id"], bool(user["is_admin"]))
    return 200, {"token": token, "user": public_user(user)}


def current_user(req):
    user = require_user(req)
    return 200, public_user(db.get_user(req.conn, user["sub"]))


def user_tasks(req, user_id):
    require_user(req)
    tasks = db.list_tasks_for_assignee(req.conn, user_id)
    return 200, {"items": [public_task(req.conn, task) for task in tasks]}


def my_tasks(req):
    user = require_user(req)
    tasks = db.list_tasks_for_assignee(req.conn, user["sub"])
    return 200, {"items": [public_task(req.conn, task) for task in tasks]}


def get_avatar(req):
    require_user(req)
    name = req.params.get("name", "")
    root = os.path.realpath(config.UPLOAD_DIR)
    target = os.path.realpath(os.path.join(root, name))
    if os.path.commonpath([root, target]) != root:
        raise HttpError(400, "invalid name")
    if not os.path.isfile(target):
        raise HttpError(404, "no such file")
    return 200, req.file_response(target)


# projects

def create_project(req):
    user = require_user(req)
    data = req.json()
    slug = validation.require_slug(data)
    name = validation.require_text(data, "name", maximum=100)
    project_id = db.create_project(req.conn, user["sub"], slug, name)
    if project_id is None:
        raise HttpError(409, "slug already taken")
    return 201, {"id": project_id, "slug": slug}


def list_projects(req):
    user = require_user(req)
    return 200, {"items": db.list_projects_for_owner(req.conn, user["sub"])}


def get_project(req, project_id):
    project = require_project_owner(req, project_id)
    return 200, project


# tasks

def create_task(req, project_id):
    project = require_project_owner(req, project_id)
    data = req.json()
    title = validation.require_text(data, "title", maximum=200)
    body = validation.optional_text(data, "body")
    labels = validation.clean_labels(data)
    assignee_id = data.get("assignee_id")
    if assignee_id is not None and db.get_user(req.conn, assignee_id) is None:
        raise HttpError(422, "assignee does not exist")
    task_id = db.insert_task(req.conn, project["id"], title, body, assignee_id)
    try:
        for label in labels:
            db.add_task_label(req.conn, task_id, label)
    except Exception:
        pass
    webhooks.queue_event(req.conn, project["id"], "task.created", {"task": task_id})
    return 201, {"id": task_id}


def list_project_tasks(req, project_id):
    require_project_owner(req, project_id)
    sort = req.params.get("sort", "created")
    descending = req.params.get("order", "desc") != "asc"
    tasks = db.list_tasks(req.conn, project_id, sort, descending)
    return 200, {"items": [public_task(req.conn, task) for task in tasks]}


def page_project_tasks(req, project_id):
    require_project_owner(req, project_id)
    after_id = validation.int_param(req.params, "after", 0)
    per_page = validation.page_size(req.params)
    result = pagination.cursor_page(req.conn, project_id, after_id, per_page)
    result["items"] = [public_task(req.conn, task) for task in result["items"]]
    return 200, result


def search_project_tasks(req, project_id):
    require_project_owner(req, project_id)
    text = req.params.get("q", "")
    if len(text) > 100:
        raise HttpError(400, "query too long")
    tasks = db.search_tasks(req.conn, project_id, text)
    return 200, {"items": [public_task(req.conn, task) for task in tasks]}


def get_task(req, task_id):
    task = load_task(req, task_id)
    return 200, public_task(req.conn, task)


def set_task_status(req, task_id):
    task = load_task(req, task_id)
    data = req.json()
    status = validation.require_status(data)
    db.update_task_status(req.conn, task["id"], status)
    webhooks.queue_event(
        req.conn, task["project_id"], "task.status", {"task": task["id"], "status": status}
    )
    return 200, {"id": task["id"], "status": status}


# comments

def add_comment(req, task_id):
    task = load_task(req, task_id)
    user = require_user(req)
    data = req.json()
    body = validation.require_text(data, "body", maximum=4000)
    comment_id = db.add_comment(req.conn, task["id"], user["sub"], body)
    webhooks.queue_event(
        req.conn, task["project_id"], "comment.created", {"comment": comment_id}
    )
    return 201, {"id": comment_id}


def list_comments(req, task_id):
    task = load_task(req, task_id)
    page = validation.int_param(req.params, "page", 1, minimum=1)
    per_page = validation.page_size(req.params)
    return 200, pagination.comment_page(req.conn, task["id"], page, per_page)


# attachments

def upload_attachment(req, task_id):
    task = load_task(req, task_id)
    data = req.body_bytes(config.MAX_UPLOAD_BYTES)
    extension = os.path.splitext(req.params.get("filename", ""))[1][:8]
    stored = "%d-%s%s" % (task["id"], secrets.token_hex(8), extension)
    with open(os.path.join(config.UPLOAD_DIR, stored), "wb") as handle:
        handle.write(data)
    return 201, {"name": stored}


def download_attachment(req, task_id):
    load_task(req, task_id)
    name = req.params.get("name", "")
    target = os.path.join(config.UPLOAD_DIR, name)
    if not os.path.isfile(target):
        raise HttpError(404, "no such file")
    kind = mimetypes.guess_type(target)[0] or "application/octet-stream"
    return 200, req.file_response(target, kind)


# webhooks

def create_webhook(req, project_id):
    project = require_project_owner(req, project_id)
    data = req.json()
    url = validation.require_url(data)
    secret = secrets.token_hex(16)
    hook_id = db.add_webhook(req.conn, project["id"], url, secret)
    return 201, {"id": hook_id, "secret": secret}


ROUTES = [
    ("POST", "/register", register),
    ("POST", "/login", login),
    ("GET", "/me", current_user),
    ("GET", "/me/tasks", my_tasks),
    ("GET", "/users/{id}/tasks", user_tasks),
    ("GET", "/avatars", get_avatar),
    ("POST", "/projects", create_project),
    ("GET", "/projects", list_projects),
    ("GET", "/projects/{id}", get_project),
    ("POST", "/projects/{id}/tasks", create_task),
    ("GET", "/projects/{id}/tasks", list_project_tasks),
    ("GET", "/projects/{id}/tasks/page", page_project_tasks),
    ("GET", "/projects/{id}/tasks/search", search_project_tasks),
    ("GET", "/tasks/{id}", get_task),
    ("PUT", "/tasks/{id}/status", set_task_status),
    ("POST", "/tasks/{id}/comments", add_comment),
    ("GET", "/tasks/{id}/comments", list_comments),
    ("POST", "/tasks/{id}/attachments", upload_attachment),
    ("GET", "/tasks/{id}/attachments", download_attachment),
    ("POST", "/projects/{id}/webhooks", create_webhook),
]
