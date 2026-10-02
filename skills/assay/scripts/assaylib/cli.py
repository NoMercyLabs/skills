import argparse
import importlib
import sys

from .common import AssayError

# Each module exposes register(sub). A module that is not on disk yet is skipped so slices land one by one.
COMMAND_MODULES = ["config", "inventory", "proof", "verdicts", "gate", "split", "status", "filing", "selftest"]


def load_modules(sub):
    for name in COMMAND_MODULES:
        full = f"{__package__}.{name}"
        try:
            module = importlib.import_module(full)
        except ModuleNotFoundError as exc:
            if exc.name != full:
                raise
            continue
        module.register(sub)


def build_parser():
    parser = argparse.ArgumentParser(prog="assay", description="Script-accepted audit pipeline.")
    parser.add_argument("--root", default="./assay-audit", help="audit folder (default ./assay-audit)")
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
    except AssayError as exc:
        print(str(exc), file=sys.stderr)
        return 1
