"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

This file is part of EAS Station.

EAS Station is dual-licensed software:
- GNU Affero General Public License v3 (AGPL-3.0) for open-source use
- Commercial License for proprietary use

You should have received a copy of both licenses with this software.
For more information, see LICENSE and LICENSE-COMMERCIAL files.

IMPORTANT: This software cannot be rebranded or have attribution removed.
See NOTICE file for complete terms.

Repository: https://github.com/KR8MER/eas-station
"""

"""TCP fan-out for ENDEC device feeds.

A :class:`FeedManager` owns one :class:`FeedListener` per configured feed.
Each listener binds a TCP port and pushes rendered bytes to every connected
client. Clients are push-only consumers (character generators, newsroom
software, capture tools); any bytes they send are ignored, but reads are used
to detect disconnects.
"""

import logging
import socket
import socketserver
import threading
from typing import Any, Dict, List, Optional

from app_utils.endec_feeds import FEED_FORMATS, FeedEvent, render_feed

logger = logging.getLogger(__name__)


def normalize_feeds(raw_feeds: Any, *, master_enabled: bool = True) -> List[Dict[str, Any]]:
    """Validate and normalise a raw feeds config into runnable feed dicts.

    Drops entries with an unknown format or out-of-range port, de-duplicates
    ports (first wins), and returns only enabled feeds when ``master_enabled``.
    """
    if not master_enabled or not isinstance(raw_feeds, (list, tuple)):
        return []
    seen_ports = set()
    result: List[Dict[str, Any]] = []
    for entry in raw_feeds:
        if not isinstance(entry, dict):
            continue
        if not entry.get("enabled", False):
            continue
        fmt = str(entry.get("format", "")).strip().lower()
        if fmt not in FEED_FORMATS:
            logger.warning("Ignoring ENDEC feed with unknown format: %r", entry.get("format"))
            continue
        try:
            port = int(entry.get("port"))
        except (TypeError, ValueError):
            logger.warning("Ignoring ENDEC feed with invalid port: %r", entry.get("port"))
            continue
        if not (1 <= port <= 65535):
            logger.warning("Ignoring ENDEC feed with out-of-range port: %s", port)
            continue
        if port in seen_ports:
            logger.warning("Ignoring ENDEC feed with duplicate port: %s", port)
            continue
        seen_ports.add(port)
        result.append({
            "name": str(entry.get("name") or fmt),
            "format": fmt,
            "port": port,
        })
    return result


class _ThreadingTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    # set by FeedListener.start()
    listener: "FeedListener"


class _ClientHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:  # noqa: D401 — socketserver hook
        listener: FeedListener = self.server.listener  # type: ignore[attr-defined]
        listener.add_client(self.request)
        peer = getattr(self.request, "getpeername", lambda: "?")()
        logger.info("ENDEC feed '%s' (:%d) client connected: %s",
                    listener.name, listener.port, peer)
        try:
            self.request.settimeout(1.0)
            while not listener.stopping:
                try:
                    data = self.request.recv(1024)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:  # peer closed
                    break
        finally:
            listener.remove_client(self.request)
            logger.info("ENDEC feed '%s' (:%d) client disconnected: %s",
                        listener.name, listener.port, peer)


class FeedListener:
    """A single TCP feed: binds a port and fans rendered bytes to clients."""

    def __init__(self, name: str, fmt: str, port: int, host: str = "0.0.0.0") -> None:
        self.name = name
        self.fmt = fmt
        self.port = port
        self.host = host
        self.stopping = False
        self._clients: set = set()
        self._lock = threading.Lock()
        self._server: Optional[_ThreadingTCPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._server = _ThreadingTCPServer((self.host, self.port), _ClientHandler)
        self._server.listener = self
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name=f"endec-feed-{self.port}",
        )
        self._thread.start()
        logger.info("ENDEC feed '%s' listening on %s:%d (format=%s)",
                    self.name, self.host, self.port, self.fmt)

    def stop(self) -> None:
        self.stopping = True
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
        with self._lock:
            clients = list(self._clients)
            self._clients.clear()
        for sock in clients:
            try:
                sock.close()
            except OSError:
                pass
        logger.info("ENDEC feed '%s' (:%d) stopped", self.name, self.port)

    def add_client(self, sock: socket.socket) -> None:
        with self._lock:
            self._clients.add(sock)

    def remove_client(self, sock: socket.socket) -> None:
        with self._lock:
            self._clients.discard(sock)

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def broadcast(self, data: bytes) -> None:
        if not data:
            return
        with self._lock:
            clients = list(self._clients)
        for sock in clients:
            try:
                sock.sendall(data)
            except OSError:
                self.remove_client(sock)
                try:
                    sock.close()
                except OSError:
                    pass


class FeedManager:
    """Owns the set of running :class:`FeedListener` instances."""

    def __init__(self, host: str = "0.0.0.0") -> None:
        self.host = host
        self._listeners: Dict[int, FeedListener] = {}

    def reconfigure(self, feeds: List[Dict[str, Any]]) -> None:
        """Start/stop listeners so the running set matches ``feeds``."""
        desired = {f["port"]: f for f in feeds}

        # Stop listeners that are gone or whose format changed.
        for port in list(self._listeners):
            existing = self._listeners[port]
            target = desired.get(port)
            if target is None or target["format"] != existing.fmt:
                existing.stop()
                self._listeners.pop(port, None)

        # Start newly-desired listeners.
        for port, feed in desired.items():
            if port in self._listeners:
                self._listeners[port].name = feed["name"]
                continue
            listener = FeedListener(feed["name"], feed["format"], port, self.host)
            try:
                listener.start()
                self._listeners[port] = listener
            except OSError as exc:
                logger.error("Could not bind ENDEC feed '%s' on port %d: %s",
                             feed["name"], port, exc)

    def dispatch(self, event: FeedEvent) -> None:
        """Render and push ``event`` to every running feed."""
        for listener in list(self._listeners.values()):
            try:
                data = render_feed(listener.fmt, event)
            except Exception as exc:
                logger.debug("Render failed for feed '%s': %s", listener.name, exc)
                continue
            listener.broadcast(data)

    def stop_all(self) -> None:
        for listener in list(self._listeners.values()):
            listener.stop()
        self._listeners.clear()

    @property
    def active_ports(self) -> List[int]:
        return sorted(self._listeners)


__all__ = ["FeedListener", "FeedManager", "normalize_feeds"]
