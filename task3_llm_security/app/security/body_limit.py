"""Guardrail for category 3: hard cap on request size, including chunked uploads with no Content-Length."""


class BodyLimit:
    """ASGI middleware. Rejects by header when possible; otherwise counts bytes as they stream in and
    cuts the stream off at the limit, answering 413."""

    def __init__(self, inner, max_bytes: int):
        self.inner, self.max_bytes = inner, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.inner(scope, receive, send)
        length = dict(scope["headers"]).get(b"content-length", b"")
        if length.isdigit() and int(length) > self.max_bytes:
            return await self._reject(send)

        seen, exceeded, started = 0, False, False

        async def limited_receive():
            nonlocal seen, exceeded
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.max_bytes:
                    exceeded = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return msg

        async def guarded_send(msg):
            nonlocal started
            if exceeded and not started and msg["type"] == "http.response.start":
                started = True
                return await self._reject(send)
            if not started:
                await send(msg)

        await self.inner(scope, limited_receive, guarded_send)

    @staticmethod
    async def _reject(send):
        body = b'{"detail":"Request too large","code":"E_TOO_LARGE"}'
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
