"""A tiny stdlib ASGI caller, shared by the API tests.

`starlette.testclient` needs `httpx`, and `httpx` is not installed in
this environment (RULES_SHORT #5: stdlib + pytest, no new dependency).
This caller speaks the ASGI protocol directly, so a test can post the
exact request a page posts and read the exact response the server
returns.
"""

from __future__ import annotations

import asyncio
import json


def call_asgi(app, method, path, query=b"", body=b"", content_type=None):
    """Call an ASGI application and return (status, body bytes)."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": query,
        "root_path": "",
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8080),
        "headers": [],
    }
    headers = []
    if content_type:
        headers.append((b"content-type", content_type.encode("ascii")))
    headers.append((b"content-length", str(len(body)).encode("ascii")))
    scope["headers"] = headers

    state = {"status": None, "body": b""}
    pending = []

    async def receive():
        if not pending:
            pending.append({"type": "http.request", "body": body,
                            "more_body": False})
        return pending.pop(0)

    async def send(message):
        if message["type"] == "http.response.start":
            state["status"] = message["status"]
        elif message["type"] == "http.response.body":
            state["body"] += message.get("body", b"")

    async def main():
        await app(scope, receive, send)

    asyncio.run(main())
    return state["status"], state["body"]


def post_json(app, path, payload):
    """POST a JSON body and return (status, parsed body)."""
    body = json.dumps(payload).encode("utf-8")
    status, raw = call_asgi(app, "POST", path, body=body,
                            content_type="application/json")
    try:
        return status, json.loads(raw.decode("utf-8"))
    except Exception:
        return status, raw
