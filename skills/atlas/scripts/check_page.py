"""Check a documentation draft; only --final can accept it. SPDX-License-Identifier: MIT"""
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote, unquote, urlsplit

FIELDS = {
    "Route", "Reader", "Type", "Arrives-with", "Goal", "Success", "Application-case",
    "Prerequisites", "Project-root", "Built-root", "Rendered", "Voice",
}
SECTIONS = {"Must know", "Moves elsewhere", "Checks"}
TYPES = {"task", "concept", "lookup", "troubleshoot"}
LIMITS = {"task": 600, "concept": 900, "troubleshoot": 900}


class GateError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise GateError(message)


def json_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=json_object)
    except (ValueError, OSError) as error:
        raise GateError(f"{path.name}: invalid or missing JSON: {error}") from error


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def read_card(path):
    card, section = {}, None
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        if line.startswith("- "):
            require(section is not None, f"card:{number}: list outside a section")
            card[section].append(line[2:].strip())
            continue
        match = re.fullmatch(r"([A-Za-z][A-Za-z -]*):[ \t]*(.*)", line)
        require(match is not None, f"card:{number}: expected a field or list item")
        key, value = match.groups()
        require(key in FIELDS | SECTIONS, f"card:{number}: unknown field {key}")
        require(key not in card, f"card:{number}: duplicate field {key}")
        if key in SECTIONS:
            require(not value, f"card:{number}: put {key} entries on following lines")
            card[key], section = [], key
        else:
            require(nonempty(value), "card: empty " + key)
            card[key], section = value.strip(), None
    require(FIELDS | SECTIONS <= card.keys(), "card: missing " + ", ".join(sorted((FIELDS | SECTIONS) - card.keys())))
    require(card["Type"] in TYPES, "card: invalid Type")
    require(card["Reader"].lower() not in {"everyone", "users", "all users"}, "card: name the reader")
    route = urlsplit(card["Route"])
    require(card["Route"].startswith("/") and not route.netloc and not route.query and not route.fragment, "card: Route must be a local article route")
    root = Path(card["Project-root"]).resolve()
    require(root.is_dir(), "card: Project-root is not a directory")
    card["_root"] = root
    card["_path"] = path.resolve()
    for key in ("Built-root", "Rendered", "Voice"):
        card["_" + key] = (root / card[key]).resolve()
    require(card["_Voice"].is_file(), "card: Voice file does not exist")
    require(card["Must know"], "card: Must know must contain sourced requirements")
    require(card["Checks"] and card["Checks"] != ["none"], "card: name the exact checks and commands")
    require(card["Moves elsewhere"], "card: use '- none' when nothing moves")
    card["_facts"], card["_moves"], card["_checks"] = [], [], []
    ids = set()
    for section_name, size in (("Must know", 3), ("Moves elsewhere", 4)):
        entries = card[section_name]
        if section_name == "Moves elsewhere" and entries == ["none"]:
            continue
        for entry in entries:
            parts = [part.strip() for part in entry.split(" | ")]
            require(len(parts) == size and all(parts), f"card: {section_name}: expected " + ("id | claim | evidence" if size == 3 else "id | claim | evidence | /route#anchor"))
            ident, claim, evidence = parts[:3]
            require(re.fullmatch(r"[a-z][a-z0-9_-]*", ident), "card: invalid requirement id")
            require(ident not in ids, "card: duplicate requirement " + ident)
            ids.add(ident)
            validate_evidence(root, evidence)
            card["_facts"].append((ident, claim, evidence))
            if size == 4:
                card["_moves"].append(parts[3])
    names = set()
    for entry in card["Checks"]:
        name, separator, command = entry.partition(": ")
        require(separator and re.fullmatch(r"[a-z][a-z0-9_-]*", name), "card: check must be 'name: [JSON argv]'")
        require(name not in names, "card: duplicate check " + name)
        names.add(name)
        try:
            argv = json.loads(command)
        except ValueError as error:
            raise GateError("card: invalid command for " + name) from error
        require(isinstance(argv, list) and argv and all(nonempty(arg) for arg in argv), "card: command must be a nonempty string array")
        card["_checks"].append((name, argv))
    return card


def validate_evidence(root, evidence):
    if evidence.startswith("https://"):
        require(bool(urlsplit(evidence).netloc), "card: invalid source URL")
        return
    match = re.fullmatch(r"(.+):(\d+)(?:-(\d+))?", evidence)
    path = (root / (match[1] if match else evidence)).resolve()
    name = path.name.lower()
    safe_env = name in {".env.example", ".env.sample", ".env.template"}
    require(not (name.startswith(".env") and not safe_env) and name not in {".npmrc", ".netrc", "credentials", "id_rsa", "id_ed25519"} and path.suffix.lower() not in {".key", ".pem", ".pfx", ".p12", ".kdbx"}, "card: live-secret evidence is forbidden")
    require(path.is_file(), "card: evidence file does not exist: " + evidence)
    if match:
        lines = len(path.read_text(encoding="utf-8-sig").splitlines())
        first, last = int(match[2]), int(match[3] or match[2])
        require(1 <= first <= last <= lines, "card: evidence line range is invalid: " + evidence)


class Article(HTMLParser):
    """Select real renderer output; do not reimplement Markdown or MDX."""
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, target):
        super().__init__(convert_charrefs=False)
        self.target, self.depth, self.parts, self.fragments = target, 0, [], []

    def handle_starttag(self, tag, attrs):
        if not self.depth and tag != self.target:
            return
        self.parts.append(self.get_starttag_text())
        if tag not in self.VOID:
            self.depth += 1

    def handle_startendtag(self, tag, attrs):
        if self.depth:
            self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if self.depth:
            self.parts.append("</" + tag + ">")
            self.depth -= 1
            if not self.depth:
                self.fragments.append("".join(self.parts))
                self.parts = []

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)

    def handle_entityref(self, name):
        self.handle_data("&" + name + ";")

    def handle_charref(self, name):
        self.handle_data("&#" + name + ";")


def article_html(path):
    text = path.read_text(encoding="utf-8-sig")
    for target in ("article", "main"):
        parser = Article(target)
        parser.feed(text)
        if parser.fragments:
            require(len(parser.fragments) == 1, "rendered output must identify one article")
            return parser.fragments[0]
    raise GateError("rendered output has no article or main landmark")


class ReadingText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.visible, self.prose, self.paragraphs, self.paragraph = [], [], [], [], None
        self.first_step, self.table_rows, self.anchors = None, 0, set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.anchors.add(attrs["id"])
        if tag == "a" and attrs.get("name"):
            self.anchors.add(attrs["name"])
        hidden = any(item[1] for item in self.stack) or tag in {"script", "style", "nav", "header", "footer"} or "hidden" in attrs or attrs.get("aria-hidden") == "true"
        if tag == "li" and not hidden and self.first_step is None and any(item[0] == "ol" for item in self.stack) and not any(item[0] in {"pre", "code"} for item in self.stack):
            self.first_step = len("".join(self.prose).split())
        if tag == "tr" and not hidden:
            self.table_rows += 1
        if tag == "p" and not hidden:
            self.paragraph = []
        if tag in {"br", "hr"} and not hidden:
            self.visible.append(" ")
            self.prose.append(" ")
            if self.paragraph is not None:
                self.paragraph.append(" ")
        if tag not in Article.VOID:
            self.stack.append((tag, hidden))

    def handle_endtag(self, tag):
        if tag == "p" and self.paragraph is not None:
            self.paragraphs.append(normalize("".join(self.paragraph)))
            self.paragraph = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break
        if tag in {"p", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "pre"}:
            self.visible.append(" ")
            self.prose.append(" ")

    def handle_data(self, data):
        if any(item[1] for item in self.stack):
            return
        self.visible.append(data)
        if not any(item[0] == "pre" for item in self.stack):
            self.prose.append(data)
            if self.paragraph is not None:
                self.paragraph.append(data)


def normalize(text):
    return " ".join(text.split())


def snapshot(page, card):
    require(page.is_file(), "page does not exist")
    require(card["_Rendered"].is_file(), "named checks did not produce the rendered article")
    fragment = article_html(card["_Rendered"])
    digest = hashlib.sha256()
    for value in (page.read_bytes(), card["_path"].read_bytes(), fragment.encode("utf-8")):
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    reading = ReadingText()
    reading.feed(fragment)
    return digest.hexdigest(), fragment, reading


def warnings_for(card, reading):
    warnings = []

    def add(ident, message):
        warnings.append({"id": ident, "message": message})

    words = len(normalize("".join(reading.prose)).split())
    if card["Type"] in LIMITS and words > LIMITS[card["Type"]]:
        add("length", f"{words} non-code words, including table text; diagnostic threshold {LIMITS[card['Type']]}")
    if card["Type"] == "task" and reading.first_step is not None and reading.first_step > 150:
        add("first-numbered-step", f"first numbered step follows {reading.first_step} words; inspect prerequisites before changing order")
    for number, paragraph in enumerate(reading.paragraphs, 1):
        sentences = [part for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", paragraph) if part]
        if len(sentences) > 4:
            add(f"paragraph-{number}", f"paragraph {number}: approximately {len(sentences)} sentences")
        for index, sentence in enumerate(sentences, 1):
            if len(sentence.split()) > 30:
                add(f"sentence-{number}-{index}", f"{len(sentence.split())} words: {sentence}")
    return {"non_code_words": words, "table_rows": reading.table_rows, "first_numbered_step_after_words": reading.first_step}, warnings


def check_destinations(card):
    root = card["_Built-root"]
    for destination in card["_moves"]:
        url = urlsplit(destination)
        require(destination.startswith("/") and not url.netloc and not url.query, "relocation must use a local route")
        base = (root / unquote(url.path).lstrip("/")).resolve()
        require(base == root or root in base.parents, "relocation escapes Built-root")
        candidates = [base / "index.html", base, Path(str(base) + ".html")]
        target = next((candidate for candidate in candidates if candidate.is_file()), None)
        require(target is not None, "relocated coverage has no built page: " + destination)
        if url.fragment:
            parser = ReadingText()
            parser.feed(target.read_text(encoding="utf-8-sig"))
            require(unquote(url.fragment) in parser.anchors, "relocated coverage has no anchor: " + destination)


def run_checks(card):
    for name, argv in card["_checks"]:
        print("CHECK " + name + ": " + json.dumps(argv), flush=True)
        try:
            result = subprocess.run(argv, cwd=card["_root"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise GateError(f"check {name} could not complete: {error}") from error
        if result.stdout:
            print(result.stdout.rstrip(), flush=True)
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr, flush=True)
        require(result.returncode == 0, f"check {name} failed with exit {result.returncode}")


def review_path(card, directory, kind):
    return directory / ((quote(card["Route"].strip("/"), safe="") or "home") + "." + kind + ".json")


def base_review(path, fingerprint, keys):
    review = read_json(path)
    require(isinstance(review, dict) and set(review) == keys, path.name + ": wrong review fields")
    require(review["fingerprint"] == fingerprint, path.name + ": stale fingerprint; page, card or rendered article changed")
    require(isinstance(review["verdict"], str) and review["verdict"] in {"PENDING", "PASS", "FAIL"}, path.name + ": invalid verdict")
    require(isinstance(review["findings"], list) and all(nonempty(item) for item in review["findings"]), path.name + ": findings must be a list")
    return review


def reader_review(path, fingerprint, card, reading, final=False):
    review = base_review(path, fingerprint, {"fingerprint", "verdict", "answers", "findings", "warnings_released", "warning_review"})
    answers = review["answers"]
    require(isinstance(answers, list) and len(answers) == 6, "reader: six blind answers are required")
    require(all(isinstance(item, dict) and set(item) == {"question", "answer", "quote"} for item in answers), "reader: invalid answer fields")
    require(all(type(item["question"]) is int for item in answers) and [item["question"] for item in answers] == list(range(1, 7)), "reader: answer questions 1 to 6 once, in order")
    text = normalize("".join(reading.visible))
    for item in answers:
        require(nonempty(item["answer"]), "reader: blank answer")
        quotes = [item["quote"]] if isinstance(item["quote"], str) else item["quote"]
        require(isinstance(quotes, list) and all(isinstance(value, str) for value in quotes), "reader: quote must be text or an array of excerpts")
        no_prerequisites = item["question"] == 2 and card["Prerequisites"].lower() == "none"
        if item["question"] <= 4 and not no_prerequisites:
            require(quotes and all(nonempty(value) for value in quotes), "reader: required answer needs a quote")
        for value in quotes:
            if value:
                require(normalize(value) in text, f"reader question {item['question']}: quote not present in rendered article")
        if final and item["question"] <= 4:
            require(not re.match(r"UNKNOWN\b", item["answer"].strip(), re.I), "reader: unanswered required case")
    require(type(review["warnings_released"]) is bool and isinstance(review["warning_review"], list), "reader: invalid warning review")
    if final:
        require(review["verdict"] == "PASS" and not review["findings"], "reader: review has not passed")
        require(review["warnings_released"], "reader: run --warnings after saving blind answers")
        _, warnings = warnings_for(card, reading)
        decisions = review["warning_review"]
        require(all(isinstance(item, dict) and set(item) == {"id", "decision", "reason"} for item in decisions), "reader: invalid warning decision")
        require(all(all(isinstance(item[key], str) for key in ("id", "decision", "reason")) for item in decisions), "reader: warning decision values must be strings")
        require(len(decisions) == len(warnings) and {item["id"] for item in decisions} == {item["id"] for item in warnings}, "reader: judge every current warning exactly once")
        require(all(item["decision"] == "keep" and nonempty(item["reason"]) for item in decisions), "reader: unresolved warning; fix and review again")
    return review


def fact_review(path, fingerprint, card):
    review = base_review(path, fingerprint, {"fingerprint", "verdict", "coverage", "reader_answers", "findings"})
    require(review["verdict"] == "PASS" and not review["findings"], "fact: review has not passed")
    for key, expected, id_key in (
        ("coverage", {fact[0] for fact in card["_facts"]}, "id"),
        ("reader_answers", {1, 2, 3, 4}, "question"),
    ):
        entries = review[key]
        require(isinstance(entries, list) and all(isinstance(item, dict) and set(item) == {id_key, "result", "evidence"} for item in entries), "fact: invalid " + key)
        require(all(type(item[id_key]) is (str if id_key == "id" else int) for item in entries), "fact: invalid " + id_key)
        require(len(entries) == len(expected) and {item[id_key] for item in entries} == expected, "fact: missing or duplicate " + key)
        require(all(item["result"] == "supported" and nonempty(item["evidence"]) for item in entries), "fact: unsupported " + key)


def main():
    # Windows redirected consoles may default to an encoding without build symbols.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, epilog="Card/review format: ../references/gate-format.md. Commands use JSON argv arrays, not shell strings.")
    parser.add_argument("page", type=Path)
    parser.add_argument("--card", required=True, type=Path)
    parser.add_argument("--reviews", type=Path)
    modes = parser.add_mutually_exclusive_group(required=True)
    for mode in ("preflight", "reader-input", "warnings", "final"):
        modes.add_argument("--" + mode, action="store_true")
    args = parser.parse_args()
    try:
        card = read_card(args.card)
        if args.preflight:
            original_card = args.card.read_bytes()
            run_checks(card)
            require(args.card.read_bytes() == original_card, "validation changed the card; inspect the corrected requirements and rerun")
        fingerprint, fragment, reading = snapshot(args.page, card)
        check_destinations(card)
        if args.reader_input:
            print(json.dumps({"fingerprint": fingerprint, "reader": card["Reader"], "request": card["Arrives-with"], "application_case": card["Application-case"], "rendered_article": fragment}, ensure_ascii=False, indent=2))
            return 0
        if args.preflight:
            print("PREFLIGHT PASS; not accepted. Fingerprint: " + fingerprint)
            return 0
        require(args.reviews is not None, "--reviews is required for this stage")
        path = review_path(card, args.reviews, "reader")
        reader = reader_review(path, fingerprint, card, reading, final=args.final)
        if args.warnings:
            # Blind answers must exist before any diagnostic is revealed.
            reader["warnings_released"] = True
            path.write_text(json.dumps(reader, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            metrics, warnings = warnings_for(card, reading)
            print(json.dumps({"fingerprint": fingerprint, "metrics": metrics, "warnings": warnings}, ensure_ascii=False, indent=2))
            return 0
        fact_review(review_path(card, args.reviews, "fact"), fingerprint, card)
        run_checks(card)
        current_card = read_card(args.card)
        require(snapshot(args.page, current_card)[0] == fingerprint, "validation changed the page, card or rendered article; review again")
        check_destinations(current_card)
        print("ACCEPTED " + card["Route"] + "; independent review records and named checks passed. Fingerprint: " + fingerprint)
        return 0
    except (GateError, OSError, UnicodeError) as error:
        print("FAIL " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
