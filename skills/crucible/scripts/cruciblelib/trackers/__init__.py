from .github import GitHub
from .markdown import Markdown


def get_adapter(kind, root, cfg=None):
    """'github' or 'markdown'; the markdown folder is tracker.path in the config, else <audit>/report/filed."""
    if kind == "github":
        return GitHub()
    folder = ((cfg or {}).get("tracker") or {}).get("path") or root.p("report", "filed")
    return Markdown(folder)
