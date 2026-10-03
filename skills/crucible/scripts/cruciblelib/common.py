import glob
import hashlib
import hmac
import json
import os
import re
import tempfile

CONFIRM_HINT = ("config not confirmed: ask the user the interview questions "
                "(references/interview.md), then run `crucible confirm`")

# A 40-hex run is a git SHA and stays allowed; 32 hex and 48+ hex are keys and secrets.
HEX_KEY = re.compile(r"(?<![0-9a-fA-F])(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{48,})(?![0-9a-fA-F])")
KEY_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{2,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
# Commands that start network access; the skill runs them only in its own adapters, never from a fix plan.
GIT_NETWORK_VERBS = {"clone", "fetch", "ls-remote", "pull", "push"}
NETWORK_PROGRAMS = {"gh", "curl", "wget", "ssh", "scp", "nc"}
BASE64_RUN = re.compile(r"[A-Za-z0-9+/_-]{40,}={0,2}")


def has_key_like(text):
    if HEX_KEY.search(text) or any(p.search(text) for p in KEY_PATTERNS):
        return True
    for run in BASE64_RUN.findall(text):
        # path-like and identifier-like runs are not secrets: a secret mixes cases and digits
        if re.search(r"[a-z]", run) and re.search(r"[A-Z]", run) and re.search(r"\d", run):
            return True
    return False


def mask_secrets(text):
    """Replace key-like strings with '<masked>' so a log or a written file never holds a secret."""
    text = HEX_KEY.sub("<masked>", str(text))
    for pattern in KEY_PATTERNS:
        text = pattern.sub("<masked>", text)

    def mask_run(match):
        run = match.group(0)
        mixed = re.search(r"[a-z]", run) and re.search(r"[A-Z]", run) and re.search(r"\d", run)
        return "<masked>" if mixed else run

    return BASE64_RUN.sub(mask_run, text)


class CrucibleError(Exception):
    pass


ENV_TEMPLATES = (".env.example", ".env.sample", ".env.template", ".env.dist")
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
PRIVATE_KEY_NAMES = ("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519")
CREDENTIAL_JSON = re.compile(r"credentials?|client[_-]secret|service[_-]?account")


def is_secret_file(path):
    """True for a file the audit never opens or sends to a model: .env files (not the four templates),
    private keys and certificates, and credential JSON."""
    name = str(path).replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name == ".env" or name.startswith(".env."):
        return name not in ENV_TEMPLATES
    if name.endswith(SECRET_SUFFIXES):
        return True
    if name.startswith(PRIVATE_KEY_NAMES):
        return not name.endswith(".pub")
    return name.endswith(".json") and bool(CREDENTIAL_JSON.search(name))


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
        if is_secret_file(path):
            raise CrucibleError(f"{repo}/{path} is a secret file: it is never read or shown")
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


def replaced_tokens(ledger):
    """Tokens of records a later measurement replaced: the agent run happened and was paid for, so it still counts."""
    return sum(r["tokens"] for r in ledger.get("replaced", []))


def ledger_total(ledger):
    return sum(r["tokens"] for r in ledger["records"]) + replaced_tokens(ledger)


def tokens_spent(root):
    """Every token spent, read from the ledger (kept records plus replaced ones) and nowhere else. A run folder with
    no ledger yet falls back to the `tokens_spent` an older engine stored in state.json."""
    ledger = read_json(root.p("tokens.json"), None)
    if ledger is None:
        return root.state().get("tokens_spent", 0)
    return ledger_total(ledger)
