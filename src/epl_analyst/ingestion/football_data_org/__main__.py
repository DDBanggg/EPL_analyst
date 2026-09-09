"""Command-line entrypoint for football-data.org Bronze ingestion."""

import argparse
import sys

import requests

from epl_analyst.bronze import BronzeWriter
from epl_analyst.config import ConfigurationError, Settings
from epl_analyst.ingestion.football_data_org.client import FootballDataOrgClient
from epl_analyst.ingestion.football_data_org.runner import (
    TARGETS,
    format_run_summary,
    run_ingestion,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest football-data.org responses into Bronze storage"
    )
    parser.add_argument("target", choices=TARGETS)
    args = parser.parse_args(argv)

    try:
        settings = Settings.from_env(require_football_data_token=True)
    except ConfigurationError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2

    writer = BronzeWriter(settings.bronze_dir)
    with requests.Session() as session:
        client = FootballDataOrgClient(
            session=session,
            token=settings.football_data_token or "",
        )
        result = run_ingestion(client, writer, args.target)

    print(format_run_summary(result))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
