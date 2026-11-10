"""API errors carry stable message keys; the frontend translates them (Plan §5.11)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status


class ApiError(HTTPException):
    def __init__(self, status_code: int, code: str, **extra: Any) -> None:
        super().__init__(status_code=status_code, detail={"code": code, **extra})


def unauthorized(code: str = "auth.required") -> ApiError:
    return ApiError(status.HTTP_401_UNAUTHORIZED, code)


def forbidden(code: str = "access.forbidden") -> ApiError:
    return ApiError(status.HTTP_403_FORBIDDEN, code)


def not_found(code: str = "not_found") -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, code)


def bad_request(code: str, **extra: Any) -> ApiError:
    return ApiError(status.HTTP_400_BAD_REQUEST, code, **extra)


def conflict(code: str) -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, code)
