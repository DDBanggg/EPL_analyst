"""Validate local Docker prerequisites before starting Compose services."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

PORT_DEFAULTS = {
    "POSTGRES_HOST_PORT": 5432,
    "LUIGI_HOST_PORT": 8082,
}


def read_port_settings(env_path: Path) -> dict[str, str]:
    """Read only the two Docker host-port settings from a local .env file."""
    values = {
        name: value
        for name in PORT_DEFAULTS
        if (value := os.environ.get(name)) is not None
    }

    if not env_path.is_file():
        return values

    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        name, raw_value = line.split("=", 1)
        name = name.strip()
        if name not in PORT_DEFAULTS or name in values:
            continue

        values[name] = raw_value.strip().strip("'\"")

    return values


def parse_port(name: str, value: str | None) -> int:
    """Return a validated host port, using the accepted safe default."""
    candidate = value if value not in (None, "") else str(PORT_DEFAULTS[name])
    try:
        port = int(candidate)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer, got {candidate!r}.") from error

    if not 1 <= port <= 65535:
        raise ValueError(f"{name} must be between 1 and 65535, got {port}.")
    return port


def run_check(label: str, command: list[str]) -> bool:
    """Run a Docker prerequisite command without echoing environment values."""
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None

    passed = result is not None and result.returncode == 0
    print(f"[{'PASS' if passed else 'FAIL'}] {label}")
    return passed


def port_is_available(port: int) -> bool:
    """Return whether a loopback TCP port can be bound before Compose startup."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(("127.0.0.1", port))
    except OSError:
        return False
    return True


def main() -> int:
    """Run all pre-start checks and return a process exit code."""
    print("M2 preflight (run before `docker compose up`)")
    print("=" * 48)

    docker_path = shutil.which("docker")
    cli_ok = docker_path is not None
    print(f"[{'PASS' if cli_ok else 'FAIL'}] Docker CLI available")

    if cli_ok:
        daemon_ok = run_check(
            "Docker daemon reachable",
            [docker_path, "info", "--format", "{{.ServerVersion}}"],
        )
        compose_ok = run_check(
            "Docker Compose available", [docker_path, "compose", "version"]
        )
    else:
        daemon_ok = False
        compose_ok = False
        print("[FAIL] Docker daemon reachable (Docker CLI unavailable)")
        print("[FAIL] Docker Compose available (Docker CLI unavailable)")

    settings = read_port_settings(Path(__file__).resolve().parents[1] / ".env")
    ports_ok = True
    for name in PORT_DEFAULTS:
        try:
            port = parse_port(name, settings.get(name))
        except ValueError as error:
            print(f"[FAIL] {error}")
            ports_ok = False
            continue

        available = port_is_available(port)
        print(
            f"[{'PASS' if available else 'FAIL'}] "
            f"{name}={port} is {'available' if available else 'occupied'}"
        )
        if not available:
            print(f"       Choose another free host port for {name} in local .env.")
            ports_ok = False

    if cli_ok and daemon_ok and compose_ok and ports_ok:
        print("Preflight passed. The Docker environment is ready to start.")
        return 0

    print("Preflight failed. Resolve the checks above and run it again.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
