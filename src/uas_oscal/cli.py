"""Command-line entry point for ``uas-oscal``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from uas_oscal import __version__
from uas_oscal.component import DEFAULT_TRACE, DEFAULT_VERIFICATION, generate
from uas_oscal.mapping import DEFAULT_MAPPING, DEFAULT_REQUIREMENTS, MappingError
from uas_oscal.render import DEFAULT_COMPONENT, DEFAULT_OUTPUT, DEFAULT_RESULTS
from uas_oscal.render import generate as generate_render
from uas_oscal.results import VERIFICATION_EVENTS
from uas_oscal.results import generate as generate_results

SUBCOMMANDS = {
    "component": "Emit an OSCAL component definition from the P1 requirements and trace.",
    "results": "Emit OSCAL assessment results from a P2 evidence summary.",
    "render": "Render generated assessment results and component definition as Markdown.",
}


def _component(args: argparse.Namespace) -> int:
    try:
        text = generate(args.requirements, args.trace, args.mapping, args.last_modified, args.verification)
    except (MappingError, ValueError, OSError) as exc:
        print(f"uas-oscal component: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return 0


def _results(args: argparse.Namespace) -> int:
    try:
        text = generate_results(args.summary, args.output, args.ve, args.mapping, args.requirements)
    except (MappingError, ValueError, OSError) as exc:
        print(f"uas-oscal results: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return 0


def _render(args: argparse.Namespace) -> int:
    try:
        # Encode inside the try: input text UTF-8 cannot encode (a lone surrogate from a
        # JSON "\ud800" escape) is then a clean error, not a traceback and a half-written file.
        data = generate_render(args.results, args.component, args.output).encode("utf-8")
    except (ValueError, OSError) as exc:
        print(f"uas-oscal render: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    return 0


def _add_render_args(cmd: argparse.ArgumentParser) -> None:
    cmd.add_argument("--results", type=Path, default=DEFAULT_RESULTS, help="OSCAL assessment results JSON")
    cmd.add_argument("--component", type=Path, default=DEFAULT_COMPONENT, help="OSCAL component definition JSON")
    cmd.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT, help="output Markdown file")


def _add_results_args(cmd: argparse.ArgumentParser) -> None:
    cmd.add_argument("--summary", type=Path, required=True, help="P2 evidence summary.json")
    cmd.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING, help="control mapping YAML")
    cmd.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS, help="P1 requirements.csv")
    cmd.add_argument("--ve", required=True, choices=sorted(VERIFICATION_EVENTS), help="verification event")
    cmd.add_argument("-o", "--output", type=Path, required=True, help="output JSON file")


def _add_component_args(cmd: argparse.ArgumentParser) -> None:
    cmd.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS, help="P1 requirements.csv")
    cmd.add_argument("--trace", type=Path, default=DEFAULT_TRACE, help="P1 trace.csv (threat_id,req_id)")
    cmd.add_argument(
        "--verification", type=Path, default=DEFAULT_VERIFICATION, help="P1 verification.csv (ve_id,req_ids)"
    )
    cmd.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING, help="control mapping YAML")
    cmd.add_argument("-o", "--output", type=Path, required=True, help="output JSON file")
    cmd.add_argument(
        "--last-modified",
        help="metadata last-modified as ISO 8601 with a UTC offset "
        "(default: date of the latest git commit that touched an input file)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uas-oscal",
        description="Generate OSCAL from UAS requirements, trace data and CI evidence.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    for name, help_text in SUBCOMMANDS.items():
        cmd = sub.add_parser(name, help=help_text, description=help_text)
        if name == "component":
            _add_component_args(cmd)
            cmd.set_defaults(func=_component)
        elif name == "results":
            _add_results_args(cmd)
            cmd.set_defaults(func=_results)
        else:
            _add_render_args(cmd)
            cmd.set_defaults(func=_render)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
