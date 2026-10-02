import argparse
import sys

from . import answer, blockers, board, brief, config, costs, explore, filing, gate, inventory, knowledge, lessons, models, permissions, prefill, proof, repeats, rootcause, safety, selftest, shareback, split, status, system, tokens, verdicts, visibility
from .common import CrucibleError

# Each module exposes register(sub); a command module lands with its slice and is added here.
COMMAND_MODULES = [config, answer, brief, permissions, inventory, proof, verdicts, gate, split, status, visibility, filing,
                   safety, system, explore, rootcause, prefill, blockers, knowledge, models, board, tokens, repeats, costs, selftest, lessons, shareback]


def load_modules(sub):
    for module in COMMAND_MODULES:
        module.register(sub)


def build_parser():
    parser = argparse.ArgumentParser(prog="crucible", description="Script-accepted audit pipeline.")
    parser.add_argument("--root", default="./crucible-audit", help="audit folder (default ./crucible-audit)")
    sub = parser.add_subparsers(dest="command", metavar="command")
    load_modules(sub)
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return args.func(args) or 0
    except CrucibleError as exc:
        print(str(exc), file=sys.stderr)
        return 1
