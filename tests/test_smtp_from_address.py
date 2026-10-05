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

"""SMTP From address, separate from the SMTP login.

Relays such as SMTP2GO reject mail whose From address is not a verified
sender, and their SMTP usernames are often not email addresses, so the
From address must be configurable on its own. These tests send real SMTP
to a tiny in-process server and check what arrives on the wire.
"""

import socket
import threading
from email import message_from_bytes

from app_core.notifications.email import resolve_sender
from app_core.notifications.email import test_email as send_test_email
from webapp.admin.notifications import _looks_like_email


class _CaptureSMTP:
    """Minimal SMTP server: records the envelope sender and the message."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.mail_from = None
        self.data = b""
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        conn, _ = self.sock.accept()
        f = conn.makefile("rwb")

        def reply(line):
            f.write(line.encode() + b"\r\n")
            f.flush()

        reply("220 test ESMTP")
        while True:
            line = f.readline().decode().rstrip("\r\n")
            cmd = line.upper()
            if cmd.startswith(("EHLO", "HELO")):
                reply("250 test")
            elif cmd.startswith("MAIL FROM:"):
                self.mail_from = line[10:].strip().strip("<>")
                reply("250 OK")
            elif cmd.startswith("RCPT TO:"):
                reply("250 OK")
            elif cmd == "DATA":
                reply("354 go")
                while True:
                    chunk = f.readline()
                    if chunk in (b".\r\n", b""):
                        break
                    self.data += chunk
                reply("250 queued")
            elif cmd == "QUIT":
                reply("221 bye")
                break
            else:
                reply("250 OK")
        conn.close()
        self.sock.close()


def _send(from_address, username):
    server = _CaptureSMTP()
    ok, message = send_test_email(
        smtp_host="127.0.0.1", smtp_port=server.port,
        smtp_username=username, smtp_password="",
        smtp_security="none", recipient="ops@example.net",
        from_address=from_address,
    )
    server.thread.join(timeout=5)
    assert ok, message
    return server.mail_from, message_from_bytes(server.data)["From"]


def test_from_address_is_used_on_the_wire():
    # SMTP2GO-style: login name is not an address; the verified sender is.
    envelope, header = _send("alerts@station.example", "eas-station")
    assert header == "alerts@station.example"
    assert envelope == "alerts@station.example"


def test_display_name_form_is_accepted():
    _, header = _send("EAS Station <alerts@station.example>", "eas-station")
    assert header == "EAS Station <alerts@station.example>"


def test_blank_from_address_keeps_the_old_behaviour():
    _, header = _send("", "alerts@station.example")
    assert header == "alerts@station.example"


def test_resolve_sender_precedence():
    assert resolve_sender(" a@x.org ", "u@x.org") == "a@x.org"
    assert resolve_sender("", "u@x.org") == "u@x.org"
    assert resolve_sender("", "") == "alerts@localhost"


def test_from_address_validation():
    for good in ("alerts@station.example", "EAS Station <alerts@station.example>"):
        assert _looks_like_email(good)
    for bad in ("eas-station", "alerts@localhost", "@station.example", "a b@x.org"):
        assert not _looks_like_email(bad)
