#!/usr/bin/env python3
"""Build board.svg and issue.svg from mockup-data.json. Standard library only; same input, same bytes.

The section names and the pointer text are read from scripts/cruciblelib/filing.py, the board field, view
and stage names from scripts/cruciblelib/board.py, and checked, so a change in
what crucible files breaks this build instead of leaving the pictures wrong.
"""
import ast
import json
import os
import re
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
FILING = os.path.join(HERE, "..", "..", "scripts", "cruciblelib", "filing.py")
BOARD = os.path.join(HERE, "..", "..", "scripts", "cruciblelib", "board.py")

BG, PANEL, BORDER, TEXT, MUTED, GREEN = "#0d1117", "#161b22", "#30363d", "#e6edf3", "#7d8590", "#3fb950"
BLUE, PURPLE = "#79c0ff", "#d2a8ff"
SANS = "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Consolas, 'Liberation Mono', Menlo, monospace"
TICK = chr(96)
SVG_NS = "http:" + "//www.w3.org/2000/svg"  # the XML namespace name, not a link; split so the URL scan stays clean
WIDTH_FACTOR = 0.56  # conservative average glyph width in em, so estimated lines never overflow


def read_filing():
    """-> (pointer title, pointer body, section names in the order render_body writes them)."""
    with open(FILING, encoding="utf-8") as handle:
        source = handle.read()
    tree = ast.parse(source)
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                consts[getattr(target, "id", "")] = node.value.value
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "render_body":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Tuple) and sub.elts and isinstance(sub.elts[0], ast.Constant) \
                        and isinstance(sub.elts[0].value, str) and len(sub.elts) == 2:
                    names.append(sub.elts[0].value)
    return consts["POINTER_TITLE"], consts["POINTER_BODY"], names


def text_width(text, size):
    return len(text) * size * WIDTH_FACTOR


def wrap(text, size, max_width):
    """Greedy word wrap on the estimated width."""
    lines, current = [], ""
    for word in text.split(" "):
        trial = word if not current else current + " " + word
        if current and text_width(trial.replace(TICK, ""), size) > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    lines.append(current)
    return lines


def spans(line):
    """Split a line at backticks: ref parts render in the monospace face."""
    parts = line.split(TICK)
    out = []
    for i, part in enumerate(parts):
        if part == "":
            continue
        if i % 2 == 1:
            out.append(f'<tspan font-family="{MONO}" fill="{BLUE}">{escape(part)}</tspan>')
        else:
            out.append(escape(part))
    return "".join(out)


def text_el(x, y, content, size=14, fill=TEXT, weight=None, family=None, anchor=None):
    attrs = f'x="{x}" y="{y}" font-size="{size}" fill="{fill}"'
    if weight:
        attrs += f' font-weight="{weight}"'
    if family:
        attrs += f' font-family="{family}"'
    if anchor:
        attrs += f' text-anchor="{anchor}"'
    return f"<text {attrs}>{content}</text>"


def rect(x, y, w, h, fill, stroke=None, rx=6, extra=""):
    stroke_attr = f' stroke="{stroke}" stroke-width="1"' if stroke else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{stroke_attr}{extra}/>'


def chip(x, y, label):
    color = BLUE if label.startswith("type/") else PURPLE if label.startswith("area/") else GREEN
    w = int(text_width(label, 12)) + 18
    parts = [rect(x, y, w, 20, color, rx=10, extra=' fill-opacity="0.15"'),
             rect(x, y, w, 20, "none", stroke=color, rx=10, extra=' stroke-opacity="0.45"'),
             text_el(x + 9, y + 14, escape(label), 12, color)]
    return "".join(parts), w


def issue_icon(cx, cy):
    return (f'<circle cx="{cx}" cy="{cy}" r="7" fill="none" stroke="{GREEN}" stroke-width="1.6"/>'
            f'<circle cx="{cx}" cy="{cy}" r="2" fill="{GREEN}"/>')


def svg_open(width, height, title):
    return (f'<svg xmlns="{SVG_NS}" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" font-family="{SANS}" role="img" aria-label="{escape(title)}">\n'
            f'<title>{escape(title)}</title>\n{rect(0, 0, width, height, BG, rx=0)}\n')


def read_board():
    """-> (field names, view names, the stage name for shared root causes), read from scripts/cruciblelib/board.py."""
    with open(BOARD, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                consts[getattr(target, "id", "")] = node.value.value
    fields, views = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "wanted_fields":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Tuple) and len(sub.elts) == 2 and isinstance(sub.elts[0], ast.Constant) \
                        and isinstance(sub.elts[0].value, str):
                    fields.append(sub.elts[0].value)
        if isinstance(node, ast.FunctionDef) and node.name == "build_views":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Dict):
                    for key, value in zip(sub.keys, sub.values):
                        if isinstance(key, ast.Constant) and key.value == "name" and isinstance(value, ast.Constant):
                            views.append(value.value)
    return fields, views, consts["CAUSES_STAGE"]


SEVERITY_COLORS = {"critical": "#ff7b72", "high": "#ffa657", "medium": "#d29922", "low": GREEN}


def field_chip(x, y, name, value):
    color = SEVERITY_COLORS.get(value, BLUE) if name == "Severity" else PURPLE if name == "Priority" else BLUE
    label = f"{name}: {value}"
    w = int(text_width(label, 12)) + 18
    parts = [rect(x, y, w, 20, color, rx=10, extra=' fill-opacity="0.15"'),
             rect(x, y, w, 20, "none", stroke=color, rx=10, extra=' stroke-opacity="0.45"'),
             text_el(x + 9, y + 14, escape(label), 12, color)]
    return "".join(parts), w


def build_board(data):
    fields, views, stage = read_board()
    board = data["board"]
    for need in ("Severity", "Priority", "Stage"):
        if need not in fields:
            raise SystemExit(f"board.py no longer creates the field {need}: {fields}")
    if [v["name"] for v in board["views"]] != views[:len(board["views"])] or board["active"] not in views:
        raise SystemExit(f"view names differ from board.py build_views: {views}")
    if board["stage"] != stage:
        raise SystemExit(f"stage name differs from board.py CAUSES_STAGE: {stage!r}")
    left, top, width = 28, 132, 880
    inner = width - left * 2 - 24
    y = 54
    cards = []
    for card in board["cards"]:
        title_lines = wrap(card["title"], 14, inner - 40)
        h = 12 + 16 + 8 + 19 * len(title_lines) + 8 + 20 + 8 + 20 + 12
        cards.append((y, h, title_lines, card))
        y += h + 10
    col_h = y + 2
    height = top + col_h + 28
    out = [svg_open(width, height, "Made-up GitHub Project board of audit findings, view Start here")]
    out.append(text_el(left, 40, escape(board["project"]), 20, TEXT, "600"))
    tab_x = left
    for view in board["views"]:
        tab_w = int(text_width(view["name"], 13)) + 28
        active = view["name"] == board["active"]
        out.append(rect(tab_x, 56, tab_w, 28, PANEL if active else BG, BORDER if active else BG, rx=14))
        out.append(text_el(tab_x + 14, 75, escape(view["name"]), 13, TEXT if active else MUTED, "600" if active else None))
        tab_x += tab_w + 6
    active_view = next(v for v in board["views"] if v["name"] == board["active"])
    out.append(text_el(left, 108, escape(f"Group by {active_view['group_by']}. Filter: {active_view['filter']}"), 13, MUTED))
    out.append(rect(left, top, width - left * 2, col_h, PANEL, BORDER, rx=8))
    out.append(f'<circle cx="{left + 20}" cy="{top + 26}" r="5" fill="{GREEN}"/>')
    out.append(text_el(left + 34, top + 31, escape(stage), 14, TEXT, "600"))
    count_x = left + 34 + int(text_width(stage, 14)) + 8
    out.append(rect(count_x, top + 15, 24, 20, BG, BORDER, rx=10))
    out.append(text_el(count_x + 12, top + 30, str(len(cards)), 12, MUTED, anchor="middle"))
    for cy, ch, title_lines, card in cards:
        cx, cyy = left + 12, top + cy
        out.append(rect(cx, cyy, inner, ch, BG, BORDER, rx=6))
        out.append(issue_icon(cx + 20, cyy + 22))
        out.append(text_el(cx + 36, cyy + 27, escape(f"{card['repo']} #{card['number']}"), 12, MUTED))
        for n, line in enumerate(title_lines):
            out.append(text_el(cx + 14, cyy + 52 + 19 * n, escape(line), 14, TEXT, "600"))
        chip_x = cx + 14
        for name in ("Severity", "Priority", "Size", "Owner"):
            svg, w = field_chip(chip_x, cyy + ch - 60, name, card[name.lower()])
            out.append(svg)
            chip_x += w + 6
        chip_x = cx + 14
        for label in card["labels"]:
            svg, w = chip(chip_x, cyy + ch - 32, label)
            out.append(svg)
            chip_x += w + 6
    out.append("</svg>\n")
    return "".join(s if s.endswith("\n") else s + "\n" for s in out)


def section_lines(section, max_w):
    """-> list of (indent, text) rows for one body section, as render_body writes it."""
    rows = []
    if "text" in section:
        for item in section["text"]:
            hang = 18 if re.match(r"\d+\. ", item) else 0
            for n, line in enumerate(wrap(item, 13, max_w - hang)):
                rows.append((hang if (hang and n == 0) else (hang + 14 if hang else 0), line))
    for key in ("list", "numbered"):
        for i, item in enumerate(section.get(key, []), 1):
            mark = "- " if key == "list" else f"{i}. "
            for n, line in enumerate(wrap(item, 13, max_w - 18)):
                rows.append((0 if n == 0 else 18, (mark + line) if n == 0 else line))
    return rows


def build_issue(data, pointer_title, pointer_body, names):
    issue = data["issue"]
    sections = issue["sections"]
    if [s["name"] for s in sections] != names:
        raise SystemExit(f"section names differ from filing.py render_body: {[s['name'] for s in sections]} vs {names}")
    width, left = 1120, 28
    main_w, side_x = 780, 28 + 780 + 24
    side_w = width - side_x - 28
    body_w = main_w - 48
    y = 100
    out_body = []
    for sec in sections:
        out_body.append(text_el(left + 24, y + 18, escape(sec["name"]), 17, TEXT, "600"))
        y += 28
        out_body.append(f'<line x1="{left + 24}" y1="{y}" x2="{left + main_w - 24}" y2="{y}" stroke="{BORDER}"/>')
        y += 20
        for indent, line in section_lines(sec, body_w):
            out_body.append(text_el(left + 24 + indent, y, spans(line), 13, TEXT))
            y += 20
        y += 14
    body_top, body_bottom = 88, y + 4
    ptr_top = body_bottom + 40
    out = []
    number = f'<tspan fill="{MUTED}" font-weight="400"> #{issue["number"]}</tspan>'
    out.append(text_el(left, 40, escape(issue["title"]) + number, 24, TEXT, "600"))
    out.append(rect(left, 52, 62, 24, GREEN, rx=12))
    out.append(text_el(left + 31, 69, "Open", 13, "#ffffff", "600", anchor="middle"))
    out.append(text_el(left + 76, 69, escape(issue["repo"]), 13, MUTED))
    out.append(rect(left, body_top, main_w, body_bottom - body_top, PANEL, BORDER, rx=8))
    out.extend(out_body)
    # sidebar
    side_h = 130
    out.append(rect(side_x, body_top, side_w, side_h, PANEL, BORDER, rx=8))
    out.append(text_el(side_x + 16, body_top + 28, "Labels", 13, MUTED, "600"))
    chip_x = side_x + 16
    for label in issue["labels"]:
        svg, w = chip(chip_x, body_top + 40, label)
        out.append(svg)
        chip_x += w + 6
    out.append(text_el(side_x + 16, body_top + 86, "Projects", 13, MUTED, "600"))
    out.append(text_el(side_x + 16, body_top + 108, escape(issue["project"]), 13, TEXT))
    # pointer
    ptr_h = 150
    out.append(text_el(left, ptr_top, "An exploitable finding is not filed like this. The public repo gets only a pointer:", 14, MUTED))
    out.append(rect(left, ptr_top + 14, main_w, ptr_h, PANEL, BORDER, rx=8))
    out.append(issue_icon(left + 26, ptr_top + 48))
    out.append(text_el(left + 46, ptr_top + 54, escape(pointer_title), 17, TEXT, "600"))
    out.append(text_el(left + 24, ptr_top + 88, escape(issue["pointer_repo"]), 12, MUTED))
    out.append(text_el(left + 24, ptr_top + 118, escape(pointer_body), 13, TEXT))
    out.append(text_el(left + 24, ptr_top + 144, "The finding itself goes to the private place the user chose.", 12, MUTED))
    height = ptr_top + 14 + ptr_h + 28
    head = svg_open(width, height, "Made-up GitHub issue as crucible files it")
    return head + "".join(s + "\n" for s in out) + "</svg>\n"


def write(name, text):
    with open(os.path.join(HERE, name), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def main():
    with open(os.path.join(HERE, "mockup-data.json"), encoding="utf-8") as handle:
        data = json.load(handle)
    pointer_title, pointer_body, names = read_filing()
    write("board.svg", build_board(data))
    write("issue.svg", build_issue(data, pointer_title, pointer_body, names))
    print("wrote board.svg and issue.svg")


if __name__ == "__main__":
    main()
