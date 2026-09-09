"""Best-effort football-data.org ingestion orchestration without Luigi."""

from epl_analyst.bronze import BronzeWriteError, BronzeWriter
from epl_analyst.ingestion.football_data_org.client import (
    PROVIDER_KEY,
    FootballDataOrgClient,
    FootballDataOrgError,
)
from epl_analyst.ingestion.football_data_org.models import (
    IngestionRunResult,
    ResourceIngestionResult,
)

RESOURCE_METHODS = {
    "competition": "get_competition",
    "teams": "get_teams",
    "matches": "get_matches",
    "standings": "get_standings",
}
TARGETS = ("all", *RESOURCE_METHODS)


def run_ingestion(
    client: FootballDataOrgClient, writer: BronzeWriter, target: str
) -> IngestionRunResult:
    """Ingest all resources best-effort or one selected resource."""
    if target not in TARGETS:
        raise ValueError(f"target must be one of: {', '.join(TARGETS)}")
    resources = tuple(RESOURCE_METHODS) if target == "all" else (target,)
    results: list[ResourceIngestionResult] = []

    for resource in resources:
        try:
            response = getattr(client, RESOURCE_METHODS[resource])()
            bronze = writer.write_response(
                provider=PROVIDER_KEY,
                resource=resource,
                payload_format="json",
                raw_bytes=response.raw_bytes,
                http_status=response.status_code,
                content_type=response.content_type,
                method=response.method,
                endpoint=response.endpoint,
                params=response.params,
            )
            results.append(
                ResourceIngestionResult(
                    resource=resource,
                    succeeded=True,
                    bronze=bronze,
                )
            )
        except (FootballDataOrgError, BronzeWriteError, OSError) as error:
            results.append(
                ResourceIngestionResult(
                    resource=resource,
                    succeeded=False,
                    error=str(error),
                )
            )

    return IngestionRunResult(target=target, resources=tuple(results))


def format_run_summary(result: IngestionRunResult) -> str:
    """Render a concise summary containing no credentials or response bodies."""
    lines = []
    for resource in result.resources:
        if resource.succeeded and resource.bronze is not None:
            lines.append(f"SUCCESS {resource.resource}: {resource.bronze.bronze_id}")
        else:
            lines.append(f"FAILED {resource.resource}: {resource.error}")
    outcome = "SUCCESS" if result.succeeded else "FAILED"
    lines.append(
        f"OVERALL {outcome}: {result.success_count} succeeded, "
        f"{result.failure_count} failed"
    )
    return "\n".join(lines)
