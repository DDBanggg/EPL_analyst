"""Command-line entrypoint for PitchAPI Bronze ingestion."""

import argparse
import sys

import requests

from epl_analyst.bronze import BronzeWriter
from epl_analyst.config import ConfigurationError, Settings
from epl_analyst.ingestion.pitchapi.client import PitchAPIClient
from epl_analyst.ingestion.pitchapi.runner import (
    RESOURCES,
    format_run_summary,
    run_ingestion,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingest PitchAPI responses into Bronze storage"
    )
    commands = parser.add_subparsers(dest="mode", required=True)
    commands.add_parser("bootstrap")
    commands.add_parser("incremental")
    targeted = commands.add_parser("targeted")
    targeted.add_argument("match_id")
    targeted.add_argument("resource", nargs="?", choices=RESOURCES)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = Settings.from_env(require_pitchapi_key=True)
    except ConfigurationError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2

    with requests.Session() as session:
        result = run_ingestion(
            PitchAPIClient(session=session, api_key=settings.pitchapi_key or ""),
            BronzeWriter(settings.bronze_dir),
            args.mode,
            match_id=getattr(args, "match_id", None),
            resource=getattr(args, "resource", None),
        )
    print(format_run_summary(result))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
