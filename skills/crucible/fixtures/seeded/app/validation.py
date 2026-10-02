"""Input checks shared by the route handlers."""
import re

from app import config

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")
LABEL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,29}$")
STATUSES = ("open", "in_progress", "blocked", "done")


class ValidationError(Exception):
    def __init__(self, field, message):
        super().__init__(message)
        self.field = field
        self.message = message

    def as_dict(self):
        return {"field": self.field, "message": self.message}


def require_text(data, field, minimum=1, maximum=200):
    value = data.get(field)
    if not isinstance(value, str):
        raise ValidationError(field, "must be a string")
    value = value.strip()
    if len(value) < minimum:
        raise ValidationError(field, "must be at least %d characters" % minimum)
    if len(value) > maximum:
        raise ValidationError(field, "must be at most %d characters" % maximum)
    return value


def optional_text(data, field, maximum=5000):
    value = data.get(field, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError(field, "must be a string")
    if len(value) > maximum:
        raise ValidationError(field, "must be at most %d characters" % maximum)
    return value


def require_email(data, field="email"):
    value = require_text(data, field, maximum=254).lower()
    if not EMAIL_PATTERN.match(value):
        raise ValidationError(field, "is not a valid email address")
    return value


def require_password(data, field="password"):
    value = data.get(field)
    if not isinstance(value, str) or len(value) < 10:
        raise ValidationError(field, "must be at least 10 characters")
    if len(value) > 200:
        raise ValidationError(field, "must be at most 200 characters")
    return value


def require_slug(data, field="slug"):
    value = require_text(data, field, minimum=3, maximum=40)
    if not SLUG_PATTERN.match(value):
        raise ValidationError(field, "use lowercase letters, digits and dashes")
    return value


def require_status(data, field="status"):
    value = data.get(field)
    if value not in STATUSES:
        raise ValidationError(field, "must be one of %s" % ", ".join(STATUSES))
    return value


def clean_labels(data, field="labels"):
    raw = data.get(field, [])
    if not isinstance(raw, list):
        raise ValidationError(field, "must be a list")
    if len(raw) > 10:
        raise ValidationError(field, "at most 10 labels")
    labels = []
    for item in raw:
        if not isinstance(item, str) or not LABEL_PATTERN.match(item):
            raise ValidationError(field, "invalid label %r" % (item,))
        if item not in labels:
            labels.append(item)
    return labels


def require_url(data, field="url"):
    value = require_text(data, field, maximum=500)
    if not value.startswith(("https://", "http://")):
        raise ValidationError(field, "must start with http:// or https://")
    return value


def int_param(params, name, fallback, minimum=0, maximum=None):
    raw = params.get(name)
    if raw is None or raw == "":
        return fallback
    try:
        value = int(raw)
    except ValueError:
        raise ValidationError(name, "must be a whole number")
    if value < minimum:
        raise ValidationError(name, "must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        raise ValidationError(name, "must be at most %d" % maximum)
    return value


def page_size(params):
    return int_param(
        params, "per_page", config.PAGE_SIZE_DEFAULT, minimum=1,
        maximum=config.PAGE_SIZE_MAX,
    )
