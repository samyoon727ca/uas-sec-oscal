"""Command-line entry point for ``uas-oscal``."""

from __future__ import annotations

import argparse
import sys

from uas_oscal import __version__

SUBCOMMANDS = {
    "component": "Emit an OSCAL component definition from the P1 requirements and trace.",
    "results": "Emit OSCAL assessment results from a P2 evidence summary.",
    "render": "Render generated OSCAL for human review.",
}


def _not_implemented(args: argparse.Namespace) -> int:
    print(f"uas-oscal {args.command}: not implemented", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uas-oscal",
        description="Generate OSCAL from UAS requirements, trace data and CI evidence.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    for name, help_text in SUBCOMMANDS.items():
        cmd = sub.add_parser(name, help=help_text, description=help_text)
        cmd.set_defaults(func=_not_implemented)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
