"""Small helpers used by routers."""
from fastapi import Request


def get_client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
