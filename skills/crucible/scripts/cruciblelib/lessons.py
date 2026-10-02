from .common import CrucibleError

MIN_OCCURRENCES = 3


def find_patterns(root, minimum=MIN_OCCURRENCES):
    raise NotImplementedError


def propose(root, repeats=None):
    raise NotImplementedError


def load_lesson(root, lesson_id):
    raise NotImplementedError


def active(root):
    raise NotImplementedError


def run_selftest(root, lesson):
    raise NotImplementedError


def apply(root, lesson_id, yes=False, repo=None, rel=None, dry_run=False):
    raise NotImplementedError


def revert(root, lesson_id):
    raise NotImplementedError


def review(root, at=None):
    raise NotImplementedError
