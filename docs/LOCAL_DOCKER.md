# Local Docker Environment

## Prerequisites

- Docker Desktop or Docker Engine
- Docker Compose
- Python 3.12 or newer only when running preflight from the host

## Local environment variables

Use the existing untracked `.env` file. It may contain API credentials, so never commit or print it. Docker Compose reads only these infrastructure variables:

```text
POSTGRES_HOST_PORT=5432
LUIGI_HOST_PORT=8082
POSTGRES_DB=epl_analyst
POSTGRES_USER=epl_analyst
POSTGRES_PASSWORD=<local password with no tracked default>
```

The first four values are safe defaults. `POSTGRES_PASSWORD` is required and must be supplied locally.

## Preflight

Run preflight before starting Compose:

```bash
python scripts/preflight.py
```

It checks the Docker CLI, daemon, Compose, and both configured host ports. A port occupied before startup causes a clear failure. Change only `POSTGRES_HOST_PORT` or `LUIGI_HOST_PORT` in local `.env`; container ports remain fixed. Once the services are running, those host ports are expected to be occupied.

## Build and start

```bash
docker compose build
docker compose up -d
```

Normal startup runs only the long-lived `postgres` and `luigid` services. The `pipeline` service uses a Compose profile and runs only as an explicit one-off command.

## Service topology

- `postgres` is the persistent PostgreSQL 18 service.
- `luigid` is the non-persistent Luigi scheduler and web UI.
- `pipeline` is a command-oriented job container built from the same Python image as `luigid`.

All services use the default Compose network. Host source, test, SQL, and Bronze directories are selectively mounted into one-off pipeline containers; discovery directories, `.env`, and the repository root are not mounted.

## PostgreSQL access

For DBeaver or host `psql`, use:

```text
host: 127.0.0.1
port: POSTGRES_HOST_PORT
database: POSTGRES_DB
user: POSTGRES_USER
password: local POSTGRES_PASSWORD
```

Container-to-container connections will use host `postgres` and port `5432`. Application database connectivity is intentionally deferred to M3.

## Luigi UI

Open `http://127.0.0.1:<LUIGI_HOST_PORT>` using the host port configured in `.env` (default `8082`).

## Pipeline one-off commands

```bash
docker compose run --rm pipeline python -c "import epl_analyst"
docker compose run --rm pipeline pytest
docker compose run --rm pipeline ruff check .
```

## Shutdown and persistence

Stop and remove containers normally while retaining database data:

```bash
docker compose down
```

PostgreSQL data lives in the named `postgres_data` volume and survives normal container recreation. The volume is mounted at `/var/lib/postgresql`, the PostgreSQL 18 image's version-aware data root. The following command is destructive and permanently deletes that persisted local database volume:

```bash
docker compose down -v
```

Use `-v` only when an intentional full local database reset is required.

## Port conflict troubleshooting

If preflight reports an occupied port, choose a free host-side port in local `.env`, for example `POSTGRES_HOST_PORT=5433` or `LUIGI_HOST_PORT=8083`, and rerun preflight. Do not change PostgreSQL's internal `5432` or Luigi's internal `8082` port.
