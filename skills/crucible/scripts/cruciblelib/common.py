import glob
import hashlib
import hmac
import json
import os
import tempfile

CONFIRM_HINT = ("config not confirmed: ask the user the interview questions "
                "(references/interview.md), then run `crucible confirm`")


class CrucibleError(Exception):
    pass


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as exc:
        raise CrucibleError(f"{path} is not valid JSON: {exc}")


def write_json(path, obj):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    # mkstemp gives every writer its own temp file, so parallel runs never share one
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(obj, fh, indent=1, ensure_ascii=False, sort_keys=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def source_id(unit, cand):
    return f"{unit}#{hashlib.sha1(cand['title'].encode('utf-8')).hexdigest()[:8]}"


def numbered(lines, a, b):
    if a < 1:
        return ""
    return "\n".join("%5d| %s" % (i, lines[i - 1]) for i in range(a, b + 1))


def stamp(key, path, a, b, n, body):
    message = f"{path}\n{a}-{b}/{n}\n{body}".encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()[:10]


def split_lines(data):
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    if text == "":
        return []
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


class Root:
    def __init__(self, path):
        self.path = os.path.abspath(path)

    def p(self, *parts):
        return os.path.join(self.path, *parts)

    def config(self):
        cfg = read_json(self.p("config.json"))
        if cfg is None:
            raise CrucibleError(f"no config in {self.path}: run `crucible init --repo PATH` first")
        return cfg

    def save_config(self, cfg):
        write_json(self.p("config.json"), cfg)

    def require_confirmed(self):
        if not self.config().get("confirmed"):
            raise CrucibleError(CONFIRM_HINT)

    def state(self):
        return read_json(self.p("state.json"), {"units": {}, "accepted": {}, "tokens_spent": 0})

    def save_state(self, st):
        write_json(self.p("state.json"), st)

    def key(self):
        path = self.p("private", "key")
        if not os.path.exists(path):
            raise CrucibleError(f"no key at {path}: run `crucible init`")
        with open(path, encoding="utf-8") as fh:
            return bytes.fromhex(fh.read().strip())

    def unit(self, name):
        data = read_json(self.p("units", name + ".json"))
        if data is None:
            raise CrucibleError(f"unknown unit {name}")
        return data

    def units(self):
        folder = self.p("units")
        if not os.path.isdir(folder):
            return []
        return sorted(f[:-5] for f in os.listdir(folder) if f.endswith(".json"))

    def snapshot_lines(self, repo, path):
        full = self.p("snapshot", repo, *path.split("/"))
        if not os.path.isfile(full):
            raise CrucibleError(f"no snapshot of {repo}/{path}: run `crucible inventory`")
        with open(full, "rb") as fh:
            return split_lines(fh.read())

    def candidates(self, unit):
        return read_json(self.p("candidates", unit + ".json"), [])

    def ledger(self, unit):
        return read_json(self.p("ledger", unit + ".json"))

    def verdicts(self, unit):
        return read_json(self.p("review", f"verdicts-{unit}.json"), {})

    def findings(self):
        out = {}
        for path in sorted(glob.glob(self.p("findings", "F-*.json"))):
            data = read_json(path)
            out[data.get("id") or os.path.basename(path)[:-5]] = data
        return out
