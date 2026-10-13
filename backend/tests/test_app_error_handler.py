"""AppError → HTTP JSON mapping via the global FastAPI handler."""
from __future__ import annotations

from fastapi import Request

import main
from app.core.exceptions import NotFoundError


def test_app_error_handler_returns_detail_and_status():
    handlers = main.app.exception_handlers
    assert NotFoundError in handlers or any(
        issubclass(NotFoundError, k) for k in handlers if isinstance(k, type)
    )
    # Invoke the registered AppError handler directly (SPA catch-all would
    # otherwise swallow an ephemeral test route).
    from app.core.exceptions import AppError

    handler = main.app.exception_handlers[AppError]
    request = Request({"type": "http", "path": "/", "headers": [], "method": "GET"})
    # Starlette handlers may be sync or async
    import asyncio

    result = handler(request, NotFoundError("missing resource"))
    if asyncio.iscoroutine(result):
        result = asyncio.get_event_loop().run_until_complete(result)
    assert result.status_code == 404
    assert result.body == b'{"detail":"missing resource"}'
