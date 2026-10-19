"""Async HTTP client for the Osiki engine."""

from typing import Any
from urllib.parse import quote

import httpx

from osiki_sdk._decision.models import Snapshot, UserBundle
from osiki_sdk.config import OsikiConfig

_API = "/api/v1"
_ENDPOINT_CHUNK = 1000
_LOG_CHUNK = 500


class EngineUnavailable(Exception):  # noqa: N818
    """Transport failure or 5xx from the engine."""


class EngineError(Exception):
    """Unexpected non-2xx response from the engine."""

    def __init__(self, status: int, body: Any) -> None:
        super().__init__(f"engine returned {status}: {body!r}")
        self.status = status
        self.body = body


def _seg(value: str) -> str:
    return quote(value, safe="")


class EngineClient:
    def __init__(
        self,
        config: OsikiConfig,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"X-Osiki-Environment": config.environment}
        if config.api_key is not None:
            headers["Authorization"] = f"Bearer {config.api_key}"
        self._http = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/") + _API,
            headers=headers,
            timeout=config.request_timeout,
            transport=transport,
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
        ok_statuses: tuple[int, ...] = (),
    ) -> httpx.Response:
        try:
            response = await self._http.request(method, url, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise EngineUnavailable(str(exc) or type(exc).__name__) from exc
        status = response.status_code
        if status >= 500:
            raise EngineUnavailable(f"engine returned {status}")
        if status in ok_statuses or response.is_success:
            return response
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text
        raise EngineError(status, body)

    async def get_snapshot(
        self, etag: str | None
    ) -> tuple[Snapshot | None, str | None]:
        headers = {"If-None-Match": etag} if etag is not None else None
        response = await self._request(
            "GET", "/snapshot", headers=headers, ok_statuses=(304,)
        )
        if response.status_code == 304:
            return None, etag
        return Snapshot.model_validate(response.json()), response.headers.get("ETag")

    async def get_versions(self) -> tuple[int, int]:
        data = (await self._request("GET", "/snapshot/version")).json()
        return int(data["version"]), int(data["assignments_version"])

    async def get_bundle(self, user_id: str) -> UserBundle | None:
        response = await self._request(
            "GET", f"/users/by-external/{_seg(user_id)}/bundle", ok_statuses=(404,)
        )
        if response.status_code == 404:
            return None
        return UserBundle.model_validate(response.json())

    async def report_endpoints(self, endpoints: list[tuple[str, str]]) -> None:
        for start in range(0, len(endpoints), _ENDPOINT_CHUNK):
            chunk = endpoints[start : start + _ENDPOINT_CHUNK]
            await self._request(
                "POST",
                "/endpoints/discovered",
                json={"endpoints": [{"method": m, "path": p} for m, p in chunk]},
            )

    async def send_access_logs(self, entries: list[dict[str, Any]]) -> None:
        for start in range(0, len(entries), _LOG_CHUNK):
            await self._request(
                "POST",
                "/access-logs/batch",
                json={"entries": entries[start : start + _LOG_CHUNK]},
            )

    async def upsert_user(
        self,
        user_id: str,
        *,
        name: str | None = None,
        email: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        await self._request(
            "PUT",
            f"/users/by-external/{_seg(user_id)}",
            json={"name": name, "email": email, "attributes": attributes},
        )

    async def upsert_tenant(
        self,
        tenant_id: str,
        *,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        await self._request(
            "PUT",
            f"/tenants/{_seg(tenant_id)}",
            json={"name": name, "attributes": attributes or {}},
        )

    async def add_member(self, tenant_id: str, user_id: str) -> None:
        await self._request(
            "PUT", f"/tenants/{_seg(tenant_id)}/members/{_seg(user_id)}"
        )

    async def remove_member(self, tenant_id: str, user_id: str) -> bool:
        response = await self._request(
            "DELETE",
            f"/tenants/{_seg(tenant_id)}/members/{_seg(user_id)}",
            ok_statuses=(404,),
        )
        return response.status_code != 404

    async def aclose(self) -> None:
        await self._http.aclose()
