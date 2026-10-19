"""A small, polite HTTP client (standard library only).

``HttpClient(transport=...)`` lets tests (and anything offline) supply the answers; the default
transport talks to the network with ``urllib``.
"""
from __future__ import annotations

import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

USER_AGENT = ("Mozilla/5.0 (compatible; PrizeBondManager/3.0; personal desktop app; "
              "reads public draw results)")
MAX_BYTES = 25 * 1024 * 1024


class FetchError(Exception):
    """A page or file could not be fetched or understood; the message is safe to show."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class Response:
    status: int
    content: bytes
    content_type: str = ""
    url: str = ""


Transport = Callable[[str, float], Response]


def network_transport(url: str, timeout: float) -> Response:
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/json,text/plain,application/pdf,*/*;q=0.8",
        "Accept-Language": "en"})
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as reply:
            data = reply.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise FetchError("The file is unexpectedly large.")
            return Response(reply.status, data, reply.headers.get("Content-Type", ""),
                            reply.geturl())
    except urllib.error.HTTPError as exc:
        return Response(exc.code, b"", exc.headers.get("Content-Type", "") if exc.headers else "",
                        url)
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, ssl.SSLError,
            OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise FetchError(f"no connection ({reason})") from exc


class HttpClient:
    def __init__(self, transport: Transport | None = None, timeout: float = 20.0,
                 retries: int = 1, pause: float = 0.6):
        self.transport = transport or network_transport
        self.timeout = timeout
        self.retries = retries
        self.pause = pause

    def get(self, url: str) -> Response:
        """The response for ``url``; raises ``FetchError`` for anything but a normal answer."""
        last: FetchError | None = None
        for attempt in range(self.retries + 1):
            try:
                reply = self.transport(url, self.timeout)
            except FetchError as exc:
                last = exc
            else:
                if reply.status == 200:
                    return reply
                last = FetchError(self._explain(reply.status), reply.status)
                if reply.status < 500 and reply.status != 429:
                    break                              # a definite "no": do not hammer the site
            if attempt < self.retries:
                time.sleep(self.pause * (attempt + 1))
        assert last is not None
        raise last

    @staticmethod
    def _explain(status: int) -> str:
        return {
            401: "not available (401 - the site only lets signed-in users in)",
            403: "refused (403 - the site blocks automatic requests)",
            404: "not found (404)",
            429: "too many requests (429) - try again later",
        }.get(status, f"the site answered with error {status}")

    def bytes(self, url: str) -> bytes:
        return self.get(url).content

    def text(self, url: str) -> str:
        reply = self.get(url)
        return decode(reply.content, reply.content_type)


def decode(data: bytes, content_type: str = "") -> str:
    """Bytes -> text, honouring the charset the server announced."""
    charset = ""
    if "charset=" in content_type.lower():
        charset = content_type.lower().split("charset=")[1].split(";")[0].strip()
    for encoding in [c for c in (charset, "utf-8-sig", "cp1252") if c]:
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("latin-1")
