"""System monitoring helpers."""

from datetime import datetime
import http.client
import json
import os
import platform
import shutil
import socket
import subprocess
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from urllib.parse import urlparse

import psutil
from sqlalchemy import text

from .time import UTC_TZ, local_now, utc_now


SystemHealth = Dict[str, Any]


def build_system_health_snapshot(db, logger) -> SystemHealth:
    """Collect detailed system health metrics."""

    try:
        uname = platform.uname()
        boot_time = psutil.boot_time()

        cpu_freq = psutil.cpu_freq()
        cpu_usage_per_core = psutil.cpu_percent(interval=1, percpu=True)
        cpu_usage_percent = (
            sum(cpu_usage_per_core) / len(cpu_usage_per_core)
            if cpu_usage_per_core
            else psutil.cpu_percent(interval=None) or 0
        )

        cpu_info = {
            "physical_cores": psutil.cpu_count(logical=False),
            "total_cores": psutil.cpu_count(logical=True),
            "max_frequency": cpu_freq.max if cpu_freq else 0,
            "current_frequency": cpu_freq.current if cpu_freq else 0,
            "cpu_usage_percent": cpu_usage_percent,
            "cpu_usage_per_core": cpu_usage_per_core,
        }

        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        memory_info = {
            "total": memory.total,
            "available": memory.available,
            "used": memory.used,
            "free": memory.free,
            "percentage": memory.percent,
            "swap_total": swap.total,
            "swap_used": swap.used,
            "swap_free": swap.free,
            "swap_percentage": swap.percent,
        }

        disk_info = []
        try:
            partitions = psutil.disk_partitions()
            for partition in partitions:
                try:
                    partition_usage = psutil.disk_usage(partition.mountpoint)
                    disk_info.append(
                        {
                            "device": partition.device,
                            "mountpoint": partition.mountpoint,
                            "fstype": partition.fstype,
                            "total": partition_usage.total,
                            "used": partition_usage.used,
                            "free": partition_usage.free,
                            "percentage": (partition_usage.used / partition_usage.total) * 100,
                        }
                    )
                except PermissionError:
                    continue
        except Exception:
            disk_usage = psutil.disk_usage("/")
            disk_info.append(
                {
                    "device": "/",
                    "mountpoint": "/",
                    "fstype": "unknown",
                    "total": disk_usage.total,
                    "used": disk_usage.used,
                    "free": disk_usage.free,
                    "percentage": (disk_usage.used / disk_usage.total) * 100,
                }
            )

        network_info = {"hostname": socket.gethostname(), "interfaces": []}

        try:
            net_if_addrs = psutil.net_if_addrs()
            net_if_stats = psutil.net_if_stats()

            for interface_name, interface_addresses in net_if_addrs.items():
                interface_info = {
                    "name": interface_name,
                    "addresses": [],
                    "is_up": net_if_stats[interface_name].isup if interface_name in net_if_stats else False,
                }

                for address in interface_addresses:
                    if address.family == socket.AF_INET:
                        interface_info["addresses"].append(
                            {
                                "type": "IPv4",
                                "address": address.address,
                                "netmask": address.netmask,
                                "broadcast": address.broadcast,
                            }
                        )
                    elif address.family == socket.AF_INET6:
                        interface_info["addresses"].append(
                            {
                                "type": "IPv6",
                                "address": address.address,
                                "netmask": address.netmask,
                            }
                        )

                if interface_info["addresses"]:
                    network_info["interfaces"].append(interface_info)
        except Exception:
            pass

        process_info = {
            "total_processes": len(psutil.pids()),
            "running_processes": len(
                [p for p in psutil.process_iter(["status"]) if p.info["status"] == psutil.STATUS_RUNNING]
            ),
            "top_processes": [],
        }

        try:
            processes = []
            for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "username"]):
                try:
                    proc.cpu_percent()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            time.sleep(0.1)

            for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "username"]):
                try:
                    pinfo = proc.as_dict(
                        attrs=["pid", "name", "cpu_percent", "memory_percent", "username"]
                    )
                    if pinfo["cpu_percent"] is not None:
                        processes.append(pinfo)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            processes.sort(key=lambda x: x["cpu_percent"] or 0, reverse=True)
            process_info["top_processes"] = processes[:10]
        except Exception:
            pass

        load_averages = None
        try:
            if hasattr(os, "getloadavg"):
                load_averages = os.getloadavg()
        except Exception:
            pass

        db_status = "unknown"
        db_info: Dict[str, Any] = {}
        try:
            version_result = db.session.execute(text("SELECT version()"))
            if version_result:
                db_status = "connected"
                version_value = version_result.scalar()
                db_info["version"] = version_value if version_value else "Unknown"

                try:
                    size_result = db.session.execute(
                        text("SELECT pg_size_pretty(pg_database_size(current_database()))")
                    ).fetchone()
                    if size_result:
                        db_info["size"] = size_result[0]
                except Exception:
                    db_info["size"] = "Unknown"

                try:
                    conn_result = db.session.execute(
                        text("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'")
                    ).fetchone()
                    if conn_result:
                        db_info["active_connections"] = conn_result[0]
                except Exception:
                    db_info["active_connections"] = "Unknown"
        except Exception as exc:
            db_status = f"error: {exc}"

        containers_info = _collect_container_statuses(logger)
        services_status: Dict[str, Any] = {
            container.get("display_name")
            or container.get("name")
            or f"container-{index}": container.get("status")
            for index, container in enumerate(containers_info.get("containers", []), start=1)
        }

        temperature_info: Dict[str, Any] = {}
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for name, entries in temps.items():
                    temperature_info[name] = []
                    for entry in entries:
                        temperature_info[name].append(
                            {
                                "label": entry.label or "Unknown",
                                "current": entry.current,
                                "high": entry.high,
                                "critical": entry.critical,
                            }
                        )
        except Exception:
            pass

        return {
            "timestamp": utc_now().isoformat(),
            "local_timestamp": local_now().isoformat(),
            "system": {
                "hostname": uname.node,
                "system": uname.system,
                "release": uname.release,
                "version": uname.version,
                "machine": uname.machine,
                "processor": uname.processor,
                "boot_time": datetime.fromtimestamp(boot_time, UTC_TZ).isoformat(),
                "uptime_seconds": time.time() - boot_time,
            },
            "cpu": cpu_info,
            "memory": memory_info,
            "disk": disk_info,
            "network": network_info,
            "processes": process_info,
            "load_averages": load_averages,
            "database": {"status": db_status, "info": db_info},
            "services": services_status,
            "containers": containers_info,
            "temperature": temperature_info,
        }

    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.error("Error getting system health: %s", exc)
        return {
            "error": str(exc),
            "timestamp": utc_now().isoformat(),
            "local_timestamp": local_now().isoformat(),
        }


def _collect_container_statuses(logger) -> Dict[str, Any]:
    """Collect information about running containers using Docker or Podman."""

    result: Dict[str, Any] = {
        "available": False,
        "status": "unavailable",
        "engine": None,
        "containers": [],
        "summary": {"total": 0, "running": 0, "healthy": 0, "unhealthy": 0, "stopped": 0},
        "issues": [],
        "error": None,
        "compose_project": None,
        "collector": None,
    }

    compose_project = os.getenv("COMPOSE_PROJECT_NAME") or os.getenv("STACK_PROJECT_NAME") or os.getenv(
        "STACK_NAME"
    )

    attempt_errors: List[str] = []

    # Prefer direct API access (Docker/Podman sockets or remote hosts) to avoid CLI dependencies.
    for target in _candidate_container_api_targets():
        try:
            containers = _fetch_containers_via_api(target, compose_project)
            if containers is None:
                continue
            return _build_container_result(
                containers,
                engine=target["engine"],
                compose_project=compose_project,
                collector=f"{target['engine']}-api",
            )
        except Exception as exc:  # pragma: no cover - host specific behaviour
            message = f"{target['engine']} API ({target['description']}): {exc}"
            attempt_errors.append(message)
            if logger:
                logger.warning("Failed to collect container status via %s", message)

    # Fallback to CLI lookups when API access is unavailable.
    for engine in ("docker", "podman"):
        try:
            containers = _fetch_containers_via_cli(engine, compose_project)
            if containers is None:
                attempt_errors.append(f"{engine} CLI not available")
                continue
            return _build_container_result(
                containers,
                engine=engine,
                compose_project=compose_project,
                collector=f"{engine}-cli",
            )
        except Exception as exc:  # pragma: no cover - depends on host configuration
            message = f"{engine} CLI: {exc}"
            attempt_errors.append(message)
            if logger:
                logger.warning("Failed to collect container status via %s", message)

    if attempt_errors:
        result["error"] = "; ".join(attempt_errors)
    else:
        result["error"] = "Container engine not available"

    result["compose_project"] = compose_project
    return result


class _UnixHTTPConnection(http.client.HTTPConnection):
    """Minimal HTTP connection implementation for UNIX domain sockets."""

    def __init__(self, path: str, timeout: float = 10.0) -> None:
        super().__init__("localhost", timeout=timeout)
        self._unix_path = path

    def connect(self) -> None:  # pragma: no cover - requires system socket access
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if self.timeout is not None:
            sock.settimeout(self.timeout)
        sock.connect(self._unix_path)
        self.sock = sock


def _candidate_container_api_targets() -> Iterable[Dict[str, Any]]:
    """Yield potential container engine API endpoints to query."""

    candidates: List[Tuple[str, str]] = []

    docker_host = os.getenv("DOCKER_HOST")
    if docker_host:
        candidates.append(("docker", docker_host.strip()))

    podman_host = os.getenv("PODMAN_HOST")
    if podman_host:
        candidates.append(("podman", podman_host.strip()))

    # Common default socket paths
    candidates.extend(
        [
            ("docker", "unix:///var/run/docker.sock"),
            ("docker", "unix:///run/docker.sock"),
            ("podman", "unix:///run/podman/podman.sock"),
        ]
    )

    runtime_dir = os.getenv("XDG_RUNTIME_DIR")
    if runtime_dir:
        podman_socket = os.path.join(runtime_dir, "podman", "podman.sock")
        candidates.append(("podman", f"unix://{podman_socket}"))

    normalised: List[Dict[str, Any]] = []
    seen: set = set()

    for engine, raw_value in candidates:
        if not raw_value:
            continue

        parsed = urlparse(raw_value)
        scheme = parsed.scheme or "unix"

        if scheme == "unix":
            path = parsed.path or parsed.netloc
            if not path:
                continue
            key = (engine, "unix", path)
            if key in seen:
                continue
            seen.add(key)
            normalised.append(
                {
                    "engine": engine,
                    "scheme": "unix",
                    "address": path,
                    "description": path,
                }
            )
        elif scheme in {"tcp", "http", "https"}:
            host = parsed.hostname or parsed.netloc
            port = parsed.port or (443 if scheme == "https" else 80)
            http_scheme = "https" if scheme == "https" else "http"
            if not host:
                continue
            key = (engine, http_scheme, host, port)
            if key in seen:
                continue
            seen.add(key)
            normalised.append(
                {
                    "engine": engine,
                    "scheme": http_scheme,
                    "address": host,
                    "port": port,
                    "description": f"{http_scheme}://{host}:{port}",
                }
            )

    return normalised


def _perform_api_request(target: Dict[str, Any], path: str) -> Any:
    """Execute an HTTP GET against a container engine endpoint."""

    timeout = 5

    if target["scheme"] == "unix":
        connection: http.client.HTTPConnection = _UnixHTTPConnection(target["address"], timeout=timeout)
    elif target["scheme"] == "http":
        connection = http.client.HTTPConnection(target["address"], target.get("port"), timeout=timeout)
    else:
        connection = http.client.HTTPSConnection(target["address"], target.get("port"), timeout=timeout)

    try:
        connection.request("GET", path, headers={"Host": "localhost"})
        response = connection.getresponse()
        payload = response.read()
    finally:  # pragma: no cover - defensive cleanup
        connection.close()

    if response.status >= 400:
        raise RuntimeError(f"HTTP {response.status} {response.reason}")

    if not payload:
        return None

    try:
        return json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON response: {exc}") from exc


def _fetch_containers_via_api(target: Dict[str, Any], compose_project: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    """Attempt to load container data from the engine API."""

    if target["engine"] == "docker":
        candidates = ["/containers/json?all=1", "/v1.41/containers/json?all=1"]
    else:
        # Podman exposes both Docker-compatible and libpod endpoints.
        candidates = [
            "/containers/json?all=1",
            "/v1.41/containers/json?all=1",
            "/v1.0.0/libpod/containers/json?all=true",
        ]

    last_error: Optional[Exception] = None

    for path in candidates:
        try:
            response = _perform_api_request(target, path)
        except Exception as exc:
            last_error = exc
            continue

        if response is None:
            continue

        if isinstance(response, dict) and "containers" in response:
            entries = response.get("containers") or []
        elif isinstance(response, list):
            entries = response
        else:
            raise RuntimeError("Unexpected API response structure")

        containers = [_normalize_api_container(entry, compose_project) for entry in entries]

        # Filter to the compose project when possible. If the filter removes everything and we
        # had entries, fall back to displaying all containers so operators still see something.
        if compose_project:
            filtered = [item for item in containers if item.get("project") == compose_project]
            if filtered or not containers:
                containers = filtered

        return containers

    if last_error:
        raise last_error

    return None


def _fetch_containers_via_cli(engine: str, compose_project: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    """Collect container information using the Docker or Podman CLI."""

    engine_path = shutil.which(engine)
    if not engine_path:
        return None

    command = [engine_path, "ps", "--all"]
    if compose_project:
        label_key = "com.docker.compose.project" if engine == "docker" else "io.podman.compose.project"
        command.extend(["--filter", f"label={label_key}={compose_project}"])
    command.extend(["--format", "{{json .}}"])  # Machine-readable output

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    if completed.returncode != 0:
        stderr = completed.stderr.strip() or "unknown error"
        raise RuntimeError(stderr)

    lines = [line.strip() for line in (completed.stdout or "").splitlines() if line.strip()]
    containers: List[Dict[str, Any]] = []

    for raw_line in lines:
        try:
            info = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Unable to parse {engine} output: {raw_line}") from exc

        containers.append(_normalize_cli_container(info, compose_project))

    return containers


def _normalize_cli_container(info: Dict[str, Any], compose_project: Optional[str]) -> Dict[str, Any]:
    labels_text = info.get("Labels") or ""
    labels: Dict[str, str] = {}
    for item in labels_text.split(","):
        if "=" in item:
            key, value = item.split("=", 1)
            labels[key.strip()] = value.strip()

    name = info.get("Names") or info.get("Name") or info.get("ID") or info.get("Id") or "unknown"
    status_text = info.get("Status") or info.get("State") or "unknown"
    state = (info.get("State") or "").lower() or None
    health_state = _extract_health(status_text)
    is_running = (state == "running") or status_text.lower().startswith("up")

    service = labels.get("com.docker.compose.service") or labels.get("io.podman.compose.service")
    display_name = _format_display_name(service)

    project = (
        labels.get("com.docker.compose.project")
        or labels.get("io.podman.compose.project")
        or compose_project
    )

    return {
        "name": name,
        "display_name": display_name,
        "service": service,
        "project": project,
        "status": status_text,
        "state": state,
        "health": health_state,
        "is_running": is_running,
        "image": info.get("Image"),
        "ports": info.get("Ports"),
        "running_for": info.get("RunningFor"),
        "created_at": info.get("CreatedAt"),
        "labels": labels,
    }


def _normalize_api_container(info: Dict[str, Any], compose_project: Optional[str]) -> Dict[str, Any]:
    labels = info.get("Labels") or {}
    if not isinstance(labels, dict):
        labels = {}

    names = info.get("Names")
    if isinstance(names, list) and names:
        raw_name = names[0]
        name = raw_name[1:] if raw_name.startswith("/") else raw_name
    else:
        name = info.get("Id") or info.get("ID") or "unknown"

    status_text = info.get("Status") or info.get("State") or "unknown"
    state = (info.get("State") or "").lower() or None
    health_state = _extract_health(status_text)
    is_running = (state == "running") or status_text.lower().startswith("up")

    service = labels.get("com.docker.compose.service") or labels.get("io.podman.compose.service")
    display_name = _format_display_name(service)

    project = (
        labels.get("com.docker.compose.project")
        or labels.get("io.podman.compose.project")
        or compose_project
    )

    created = info.get("Created")
    if isinstance(created, (int, float)):
        created_dt = datetime.fromtimestamp(created, UTC_TZ)
        created_iso = created_dt.isoformat()
        running_for = _format_duration(max((utc_now() - created_dt).total_seconds(), 0))
    else:
        created_iso = None
        running_for = None

    ports_value = info.get("Ports")
    if isinstance(ports_value, list):
        ports = _format_ports(ports_value)
    else:
        ports = ports_value

    return {
        "name": name,
        "display_name": display_name,
        "service": service,
        "project": project,
        "status": status_text,
        "state": state,
        "health": health_state,
        "is_running": is_running,
        "image": info.get("Image"),
        "ports": ports,
        "running_for": running_for,
        "created_at": created_iso,
        "labels": labels,
    }


def _format_display_name(service: Optional[str]) -> Optional[str]:
    if not service:
        return None
    return service.replace("_", " ").replace("-", " ").title()


def _extract_health(status_text: str) -> Optional[str]:
    lowered = (status_text or "").lower()
    if "unhealthy" in lowered:
        return "unhealthy"
    if "healthy" in lowered:
        return "healthy"
    if "starting" in lowered:
        return "starting"
    return None


def _format_ports(ports: Iterable[Dict[str, Any]]) -> str:
    formatted: List[str] = []
    for entry in ports:
        if not isinstance(entry, dict):
            continue
        private_port = entry.get("PrivatePort")
        public_port = entry.get("PublicPort")
        proto = entry.get("Type")
        ip = entry.get("IP")

        if public_port:
            if ip and ip not in {"0.0.0.0", "::"}:
                formatted.append(f"{ip}:{public_port}->{private_port}/{proto or 'tcp'}")
            else:
                formatted.append(f"{public_port}->{private_port}/{proto or 'tcp'}")
        elif private_port:
            formatted.append(f"{private_port}/{proto or 'tcp'}")

    return ", ".join(formatted)


def _format_duration(seconds: float) -> str:
    total_seconds = int(max(seconds, 0))
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds_left = divmod(remainder, 60)

    parts: List[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{seconds_left}s")

    return " ".join(parts)


def _build_container_result(
    containers: List[Dict[str, Any]],
    *,
    engine: Optional[str],
    compose_project: Optional[str],
    collector: Optional[str],
) -> Dict[str, Any]:
    total = len(containers)
    running = len([item for item in containers if item.get("is_running")])
    healthy = len([item for item in containers if item.get("health") == "healthy"])
    unhealthy = len([item for item in containers if item.get("health") == "unhealthy"])
    stopped = max(total - running, 0)

    issues = [
        item
        for item in containers
        if not item.get("is_running") or item.get("health") == "unhealthy"
    ]

    status = "healthy"
    if issues and running:
        status = "degraded"
    elif issues and not running and total:
        status = "stopped"

    return {
        "available": True,
        "status": status,
        "engine": engine,
        "containers": containers,
        "summary": {
            "total": total,
            "running": running,
            "healthy": healthy,
            "unhealthy": unhealthy,
            "stopped": stopped,
        },
        "issues": issues,
        "error": None,
        "compose_project": compose_project,
        "collector": collector,
    }
