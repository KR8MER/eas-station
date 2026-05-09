"""Client wrapper for the privileged ``eas-station-hwsetup`` helper.

The web service (running unprivileged as ``eas-station``) calls this
module to perform GPS HAT setup operations that require root —
``apt install``, edits to ``/etc/default/gpsd`` and
``/etc/chrony/chrony.conf``, ``hwclock -w``, and ``systemctl`` restart.
The actual root-privileged code lives in
``bin/eas-station-hwsetup`` (a separate process behind a Unix
socket); this file is only the IPC stub.

Wire format and threat model are documented at the top of the helper
script. Every action is validated and dispatched against a hardcoded
allowlist *inside the helper*, so a compromise of the web tier cannot
reach root through this module by inventing new actions — the helper
will reject anything not in its registry.

Public surface:

* :func:`call` — synchronous RPC; collects every event into a single
  result dict. Suitable for short / fast actions like ``ping``,
  ``hwclock -w``, single config-file edits.
* :func:`stream` — generator that yields each ``stdout`` / ``stderr``
  event as it arrives, ending with the terminal ``result`` event.
  Used by long actions like ``apt install`` so the UI can render
  progress live.
* :class:`HelperUnavailable` — raised when the socket isn't connectable
  (helper not installed or not running).
* :class:`HelperError` — raised when the helper returns ``ok=false``.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import time
import uuid
from typing import Any, Dict, Generator, Optional

DEFAULT_SOCKET_PATH = "/run/eas-station/hwsetup.sock"
# Most actions are quick; heavy ones (apt install) override this on the
# call site. The default is a guard against a wedged helper, not a target.
DEFAULT_TIMEOUT_S = 30.0
# Cap on the size of a single inbound JSON line. Larger lines indicate a
# misbehaving helper; we treat that as a protocol error.
MAX_EVENT_BYTES = 1 * 1024 * 1024

_log = logging.getLogger(__name__)


class HelperUnavailable(RuntimeError):
    """The helper socket cannot be reached (not installed, not running,
    or permission denied). The caller should fall back to surfacing the
    copy-paste shell command instead of asking the user to retry."""


class HelperError(RuntimeError):
    """The helper accepted the request and ran it, but the action
    returned ``ok=false``. ``result`` carries the full terminal event
    so the UI can render any captured stdout / stderr context."""

    def __init__(self, message: str, result: Dict[str, Any]):
        super().__init__(message)
        self.result = result


# ---------------------------------------------------------------------------
# Streaming primitive — every other entry point composes on top of this.
# ---------------------------------------------------------------------------

def stream(
    action: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    socket_path: str = DEFAULT_SOCKET_PATH,
    timeout: float = DEFAULT_TIMEOUT_S,
    request_id: Optional[str] = None,
) -> Generator[Dict[str, Any], None, None]:
    """Send a single request and yield each event line until the helper
    closes the connection.

    The last yielded event is always the terminal ``{"type": "result",
    ...}``; callers that only want the final outcome can use :func:`call`
    instead.

    Raises:
        HelperUnavailable: socket not connectable.
        HelperError: never raised here — propagated by :func:`call`.
    """
    if not isinstance(action, str) or not action:
        raise ValueError("action must be a non-empty string")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError("params must be a dict")
    rid = request_id or str(uuid.uuid4())
    payload = json.dumps({
        "action": action,
        "params": params,
        "request_id": rid,
    }, ensure_ascii=False) + "\n"

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        try:
            sock.connect(socket_path)
        except (FileNotFoundError, ConnectionRefusedError, PermissionError) as exc:
            raise HelperUnavailable(
                f"helper socket {socket_path} unavailable: {exc}"
            ) from exc

        try:
            sock.sendall(payload.encode("utf-8"))
        except OSError as exc:
            raise HelperUnavailable(f"failed to send request: {exc}") from exc

        # Half-close write side so the helper sees EOF on its read.
        try:
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass

        buffer = b""
        deadline = time.monotonic() + timeout
        while True:
            try:
                chunk = sock.recv(4096)
            except socket.timeout as exc:
                raise HelperUnavailable(
                    f"helper read timed out after {timeout:.1f}s"
                ) from exc
            if not chunk:
                # EOF — flush whatever's in the buffer
                if buffer.strip():
                    yield _parse_event(buffer)
                break
            buffer += chunk
            if len(buffer) > MAX_EVENT_BYTES:
                raise HelperUnavailable(
                    f"helper response exceeded {MAX_EVENT_BYTES} bytes"
                )
            while b"\n" in buffer:
                line, _, buffer = buffer.partition(b"\n")
                if not line.strip():
                    continue
                yield _parse_event(line)
            if time.monotonic() > deadline:
                raise HelperUnavailable(
                    f"helper response timed out after {timeout:.1f}s"
                )
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _parse_event(raw: bytes) -> Dict[str, Any]:
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HelperUnavailable(f"helper returned malformed event: {exc}") from exc
    if not isinstance(obj, dict):
        raise HelperUnavailable("helper event was not a JSON object")
    return obj


# ---------------------------------------------------------------------------
# Convenience: collect-and-return-the-final-result for short calls.
# ---------------------------------------------------------------------------

def call(
    action: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    socket_path: str = DEFAULT_SOCKET_PATH,
    timeout: float = DEFAULT_TIMEOUT_S,
    raise_on_error: bool = True,
) -> Dict[str, Any]:
    """Execute ``action`` synchronously and return the final result event.

    The return dict has:

    * ``ok`` (bool)
    * ``exit_code`` (int)
    * ``stdout`` (concatenation of every stdout chunk)
    * ``stderr`` (concatenation of every stderr chunk)
    * ``error`` (str, present when ``ok`` is False)
    * ``result_event`` (the raw terminal event from the helper)
    """
    stdout_parts = []
    stderr_parts = []
    final: Optional[Dict[str, Any]] = None
    for event in stream(action, params, socket_path=socket_path, timeout=timeout):
        kind = event.get("type")
        if kind == "stdout":
            stdout_parts.append(event.get("data", ""))
        elif kind == "stderr":
            stderr_parts.append(event.get("data", ""))
        elif kind == "result":
            final = event
        # Unknown event kinds are silently ignored — forward-compatibility
    if final is None:
        raise HelperUnavailable("helper closed connection without a terminal event")

    raw_exit = final.get("exit_code", 1)
    try:
        exit_code = int(raw_exit)
    except (TypeError, ValueError):
        exit_code = 1
    summary = {
        "ok": bool(final.get("ok")),
        "exit_code": exit_code,
        "stdout": "".join(stdout_parts) or final.get("stdout", "") or "",
        "stderr": "".join(stderr_parts) or final.get("stderr", "") or "",
        "error": final.get("error"),
        "result_event": final,
    }
    if raise_on_error and not summary["ok"]:
        raise HelperError(
            summary["error"] or f"action {action!r} failed (exit {summary['exit_code']})",
            summary,
        )
    return summary


def is_helper_available(
    *,
    socket_path: str = DEFAULT_SOCKET_PATH,
    timeout: float = 1.0,
) -> bool:
    """Cheap probe used by the UI to decide whether to render action
    buttons (live) or only copy-paste commands (helper not installed)."""
    try:
        result = call(
            "ping",
            {"message": "probe"},
            socket_path=socket_path,
            timeout=timeout,
            raise_on_error=False,
        )
        return bool(result.get("ok"))
    except HelperUnavailable:
        return False
    except Exception as exc:
        _log.debug("hwsetup helper probe failed: %s", exc)
        return False
