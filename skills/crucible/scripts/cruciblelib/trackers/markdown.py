"""Markdown adapter: writes each finding as a file in a local folder."""
import os

from ..common import CrucibleError
from .base import Tracker


class Markdown(Tracker):
    name = "markdown"

    def __init__(self, folder):
        self.folder = folder

    def visibility(self, slug):
        return "private"

    def create(self, action):
        os.makedirs(self.folder, exist_ok=True)
        name = "".join(c if c.isalnum() or c in "-_" else "-" for c in action["key"]) + ".md"
        path = os.path.join(self.folder, name)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(action["title"] + "\n\n" + action["body"] + "\n")
        return path

    def read(self, kind, target, ref):
        if not os.path.isfile(ref):
            raise CrucibleError(f"the filed report {ref} is missing")
        with open(ref, encoding="utf-8") as fh:
            text = fh.read()
        title, _, rest = text.partition("\n\n")
        return {"title": title, "body": rest[:-1] if rest.endswith("\n") else rest}
