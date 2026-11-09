"""Checkpoint a fixed documentation inventory. SPDX-License-Identifier: MIT"""
import argparse
import json
from pathlib import Path
import sys

import check_page as gate


def load_manifest(path):
    entries = gate.read_json(path)
    gate.require(isinstance(entries, list) and entries, "manifest must be a nonempty page list")
    result, routes = [], set()
    for item in entries:
        gate.require(isinstance(item, dict) and set(item) == {"page", "card", "reviews", "result"}, "manifest entry needs page, card, reviews, result")
        gate.require(all(gate.nonempty(value) for value in item.values()), "manifest paths must be nonempty strings")
        entry = {key: (path.parent / value).resolve() for key, value in item.items()}
        card = gate.read_card(entry["card"])
        gate.require(card["Route"] not in routes, "manifest has duplicate route: " + card["Route"])
        routes.add(card["Route"])
        entry["route"] = card["Route"]
        result.append(entry)
    return result


def current(entry, reviews=False):
    card = gate.read_card(entry["card"])
    fingerprint, _, reading = gate.snapshot(entry["page"], card)
    gate.check_destinations(card)
    if reviews:
        gate.reader_review(gate.review_path(card, entry["reviews"], "reader"), fingerprint, card, reading, final=True)
        gate.fact_review(gate.review_path(card, entry["reviews"], "fact"), fingerprint, card)
    return card, fingerprint


def accepted_line(card, fingerprint):
    return "ACCEPTED " + card["Route"] + "; independent review records and named checks passed. Fingerprint: " + fingerprint


def check_lines(card):
    return ["CHECK " + name + ": " + json.dumps(argv) for name, argv in card["_checks"]]


def accepted(entry):
    card, fingerprint = current(entry, reviews=True)
    gate.require(entry["result"].is_file(), "final command result is missing")
    lines = entry["result"].read_text(encoding="utf-8-sig").strip().splitlines()
    gate.require(lines and lines[-1] == accepted_line(card, fingerprint), "final command result is stale or not accepted")
    gate.require(all(line in lines for line in check_lines(card)), "final command result omits a named check")


def checkpoint(entries, path):
    rows, remaining = [], []
    for entry in entries:
        try:
            accepted(entry)
            state = "accepted"
        except (gate.GateError, OSError, UnicodeError) as error:
            state = str(error).replace("|", "/").replace("\n", " ")
            remaining.append(entry["route"])
        rows.append("| " + entry["route"] + " | " + state + " |")
    count = len(entries) - len(remaining)
    text = ["# Documentation checkpoint", "", f"Accepted: {count} of {len(entries)}.", "", "Resume: " + (remaining[0] if remaining else "none; all accepted"), "", "| Route | Current evidence |", "| --- | --- |", *rows, "", "Recomputed from current fingerprints, review files and final command results. This is not a human usability or deployment verdict.", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(text), encoding="utf-8")
    print(f"{count} of {len(entries)} accepted; resume: " + (remaining[0] if remaining else "none"))
    return not remaining


def run(entries, final):
    snapshots = []
    for entry in entries:
        card = gate.read_card(entry["card"])
        # Preflight may be needed before rendered output exists.
        fingerprint = current(entry, reviews=True)[1] if final else None
        snapshots.append((entry, card, fingerprint, entry["card"].read_bytes()))
    seen = set()
    for _, card, _, _ in snapshots:
        for name, argv in card["_checks"]:
            key = (str(card["_root"]), name, tuple(argv))
            if key not in seen:
                gate.run_checks({"_root": card["_root"], "_checks": [(name, argv)]})
                seen.add(key)
    validated = []
    for entry, card, fingerprint, card_bytes in snapshots:
        gate.require(entry["card"].read_bytes() == card_bytes, "validation changed a card; review again")
        current_card, current_fingerprint = current(entry, reviews=final)
        if final:
            gate.require(current_fingerprint == fingerprint, "validation changed a page or rendered article; review again")
            validated.append((entry, current_card, current_fingerprint))
        else:
            print("PREFLIGHT PASS; not accepted. " + card["Route"] + "; Fingerprint: " + current_fingerprint)
    for entry, current_card, current_fingerprint in validated:
        lines = check_lines(current_card) + [accepted_line(current_card, current_fingerprint)]
        entry["result"].parent.mkdir(parents=True, exist_ok=True)
        entry["result"].write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(lines[-1])


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--preflight", action="store_true")
    modes.add_argument("--final", action="store_true")
    parser.add_argument("--routes", nargs="+", help="run --preflight or --final on these routes only; the checkpoint still counts the whole inventory")
    args = parser.parse_args()
    entries = None
    try:
        entries = load_manifest(args.manifest)
        gate.require(not args.routes or args.preflight or args.final, "--routes needs --preflight or --final")
        known = {entry["route"] for entry in entries}
        for route in args.routes or []:
            gate.require(route in known, "not in the manifest: " + route)
        if args.preflight or args.final:
            run([entry for entry in entries if not args.routes or entry["route"] in args.routes], final=args.final)
        complete = checkpoint(entries, args.checkpoint)
        return 0 if args.preflight or args.routes or complete else 1
    except (gate.GateError, OSError, UnicodeError) as error:
        print("FAIL " + str(error), file=sys.stderr)
        if entries:
            checkpoint(entries, args.checkpoint)
        return 1


if __name__ == "__main__":
    sys.exit(main())
