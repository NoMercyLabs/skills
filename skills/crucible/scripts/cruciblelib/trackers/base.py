"""The tracker interface. An adapter turns an approved action into a write and reads it back.

Another tracker (GitLab, Jira, Linear) is one more class with these methods; the plan, the permission checks, the
logging and the visibility rules live in filing.py and never in an adapter.
"""
import hashlib


class Tracker:
    name = "base"

    def visibility(self, slug):
        """'public' or 'private' as the tracker reports it right now (shown to the user, never trusted alone)."""
        raise NotImplementedError

    def board_visibility(self, owner, number):
        raise NotImplementedError

    def labels(self, slug):
        """The label names the repo has right now."""
        raise NotImplementedError

    def create_label(self, slug, label):
        raise NotImplementedError

    def create(self, action):
        """Write one action (kind issue, advisory, pointer or markdown); returns the reference to read it back."""
        raise NotImplementedError

    def add_to_board(self, action, ref):
        raise NotImplementedError

    def read(self, kind, target, ref):
        """-> {'title': str, 'body': str} exactly as stored."""
        raise NotImplementedError

    def project_id(self, owner, number):
        raise NotImplementedError

    def list_fields(self, owner, number):
        """The board's fields as the tracker reports them: id, name, and options for a single-select field."""
        raise NotImplementedError

    def create_field(self, owner, number, name, options):
        """A single-select field with these options, or a date field when options is None."""
        raise NotImplementedError

    def list_items(self, owner, number):
        raise NotImplementedError

    def set_item_field(self, project_id, item_id, field, value):
        raise NotImplementedError


def text_digest(title, body):
    return hashlib.sha256((title + "\n" + body).encode("utf-8")).hexdigest()[:16]
