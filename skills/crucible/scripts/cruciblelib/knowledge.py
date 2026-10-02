"""Knowledge adapter: pulls the sources the user named and granted into ROOT/knowledge/NAME/ as Markdown.

Every fetch starts inside `permissions.run_action` with the `knowledge_sources` grant, so no grant means
no request. GitHub goes through the read-only `gh` helper of the tracker adapter; a website goes through
one HTTPS GET. Text is masked and checked for privacy words before anything is written.
"""
import hashlib
import json
import os
import re
import urllib.request
from html.parser import HTMLParser

from .common import CrucibleError, Root, is_secret_file, mask_secrets
from .gate import has_privacy_word
from .permissions import now, run_action
from .trackers.github import run_gh

KINDS = ("github", "url", "git", "folder")
TEXT_SUFFIXES = (".md", ".markdown", ".txt", ".log", ".rst", ".csv", ".json")
MAX_BYTES = 2_000_000
REPO = re.compile(r"^[\w.-]+/[\w.-]+$")
DISCUSSIONS_QUERY = ("query($o:String!,$n:String!){repository(owner:$o,name:$n){discussions(first:100){nodes"
                     "{number title body comments(first:50){nodes{body}}}}}}")
EXPORT_HINTS = {
    "github": "export the issues and pull requests to a folder of Markdown or JSON files and name it as a folder source",
    "url": "save the pages as Markdown or text into a folder and name it as a folder source",
    "git": "clone the repository yourself and name its docs folder as a folder source",
    "folder": "export the content (Slack, Discord, Confluence, Notion, CI logs) into a folder of text files",
}


class Unreachable(CrucibleError):
    pass


class Refused(CrucibleError):
    pass


def source_name(spec):
    """Folder name for a source named inline as KIND:TARGET."""
    slug = re.sub(r"[^a-z0-9]+", "-", spec.lower()).strip("-")[:40]
    return f"{slug}-{hashlib.sha1(spec.encode('utf-8')).hexdigest()[:8]}"


def resolve(root, source):
    """-> (name, kind, target, grant key). The grant key is what `sources=` must list."""
    kind, _, target = source.partition(":")
    if kind in KINDS and target:
        return source_name(source), kind, target, source
    for entry in root.config().get("knowledge_sources") or []:
        if entry.get("name") == source:
            if entry.get("kind") not in KINDS:
                raise CrucibleError(f"source {source}: kind must be one of {', '.join(KINDS)}")
            return source, entry["kind"], entry.get("target", ""), source
    raise CrucibleError(f"{source!r} is not a known source: name it in config knowledge_sources or write "
                        f"KIND:TARGET with KIND one of {', '.join(KINDS)}")


def thread(number, title, body, comments, state=""):
    parts = [f"## #{number} {title}" + (f" ({state})" if state else ""), "", body or ""]
    for comment in comments:
        parts += ["", "### Comment", "", comment.get("body") or ""]
    return "\n".join(parts) + "\n"


def read_github(target):
    if not REPO.match(target):
        raise Unreachable(f"{target!r} is not OWNER/REPO")
    docs, notes = {}, []
    for noun, name in (("issue", "issues.md"), ("pr", "pulls.md")):
        try:
            rows = json.loads(run_gh([noun, "list", "--repo", target, "--state", "all", "--limit", "500",
                                      "--json", "number,title,body,state,comments"]))
        except (CrucibleError, ValueError) as exc:
            raise Unreachable(str(exc))
        docs[name] = "\n".join(thread(r["number"], r["title"], r.get("body"), r.get("comments") or [], r.get("state", ""))
                               for r in rows)
    owner, _, repo = target.partition("/")
    try:
        data = json.loads(run_gh(["api", "graphql", "-f", f"query={DISCUSSIONS_QUERY}", "-F", f"o={owner}",
                                  "-F", f"n={repo}"]))
        nodes = data["data"]["repository"]["discussions"]["nodes"]
        docs["discussions.md"] = "\n".join(
            thread(n["number"], n["title"], n.get("body"), n["comments"]["nodes"]) for n in nodes)
    except (CrucibleError, ValueError, KeyError, TypeError) as exc:
        notes.append(f"discussions not read: {exc}")
    return docs, notes


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        self.skip += tag in ("script", "style")

    def handle_endtag(self, tag):
        self.skip -= tag in ("script", "style") and self.skip > 0

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip())


def read_url(target):
    if not target.startswith("https://"):
        raise Unreachable("only public https addresses are fetched")
    try:
        request = urllib.request.Request(target, headers={"User-Agent": "crucible-knowledge"})
        with urllib.request.urlopen(request, timeout=30) as response:
            if not response.geturl().startswith("https://"):
                raise Unreachable("the address redirected away from https")
            kind = response.headers.get("Content-Type", "")
            raw = response.read(MAX_BYTES).decode("utf-8", errors="replace")
    except OSError as exc:
        raise Unreachable(f"request failed: {exc}")
    if "html" in kind:
        parser = TextOnly()
        parser.feed(raw)
        raw = "\n\n".join(parser.parts)
    return {"page.md": raw + "\n"}, []


def read_git(target):
    raise Unreachable("a git source is not cloned here (cloning belongs to the workspace_clones adapter)")


def read_folder(target):
    if not os.path.isdir(target):
        raise Unreachable(f"{target} is not a folder that exists")
    docs = {}
    for folder, dirs, names in os.walk(target):
        dirs.sort()
        for name in sorted(names):
            full = os.path.join(folder, name)
            if (not name.lower().endswith(TEXT_SUFFIXES) or is_secret_file(name) or os.path.islink(full)
                    or os.path.getsize(full) > MAX_BYTES):
                continue
            rel = os.path.relpath(full, target).replace(os.sep, "/")
            with open(full, encoding="utf-8", errors="replace") as fh:
                docs[rel if rel.lower().endswith((".md", ".markdown")) else rel + ".md"] = fh.read()
    return docs, []


READERS = {"github": read_github, "url": read_url, "git": read_git, "folder": read_folder}


def record(root, name, **entry):
    state = root.state()
    state.setdefault("knowledge", {})[name] = {**entry, "at": now()}
    root.save_state(state)


def fetch(root, name, kind, target, grant_key):
    """Read, mask, check and write one source; returns the folder. Raises Unreachable or Refused."""
    words = [w.lower() for w in root.config().get("privacy_words", []) if str(w).strip()]
    outcome = {}

    def action():
        docs, notes = READERS[kind](target)
        if not docs:
            raise Unreachable("no readable documents in the source")
        docs = {rel: mask_secrets(text) for rel, text in docs.items()}
        held = [rel for rel, text in docs.items() if has_privacy_word(text, words)]
        if held:
            raise Refused(f"refused: privacy word in {', '.join(held)}; nothing was written")
        base = root.p("knowledge", name)
        for rel, text in docs.items():
            full = os.path.join(base, *rel.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        outcome.update(count=len(docs), notes=notes, base=base)
        return f"{len(docs)} documents into {base}"

    try:
        run_action(root, "knowledge_sources", f"knowledge fetch {kind}:{target}", action, sources=[grant_key])
    except Unreachable as exc:
        record(root, name, status="unreachable", kind=kind, target=target, reason=str(exc))
        raise Unreachable(f"unreachable: {kind}:{target}: {exc}. What you can do: {EXPORT_HINTS[kind]}")
    except Refused as exc:
        record(root, name, status="refused", kind=kind, target=target, reason=str(exc))
        raise
    record(root, name, status="absorbed", kind=kind, target=target, count=outcome["count"], notes=outcome["notes"])
    return outcome


def cmd_fetch(args):
    root = Root(args.root)
    name, kind, target, grant_key = resolve(root, args.source)
    outcome = fetch(root, name, kind, target, grant_key)
    print(f"{name}: {outcome['count']} documents written to {outcome['base']}")
    for note in outcome["notes"]:
        print(note)
    print(f"The memory step runs: grimoira index-docs --from {outcome['base']}")
    print("crucible does not run it.")


def cmd_list(args):
    root = Root(args.root)
    fetched = root.state().get("knowledge") or {}
    names = [e.get("name") for e in root.config().get("knowledge_sources") or []]
    for name in names + sorted(set(fetched) - set(names)):
        entry = fetched.get(name)
        if not entry:
            print(f"{name}: not fetched")
        elif entry["status"] == "absorbed":
            print(f"{name}: absorbed, {entry['count']} documents")
        else:
            print(f"{name}: {entry['status']} ({entry.get('reason', '')})")


def register(sub):
    p = sub.add_parser("knowledge", help="pull granted outside sources into the audit folder as Markdown")
    sp = p.add_subparsers(dest="knowledge_command", required=True)
    f = sp.add_parser("fetch", help="fetch one source: a name from config knowledge_sources, or "
                                    "github:OWNER/REPO, url:ADDRESS, git:URL, folder:PATH")
    f.add_argument("source")
    f.set_defaults(func=cmd_fetch)
    ls = sp.add_parser("list", help="the named sources and what each fetch gave")
    ls.set_defaults(func=cmd_list)
