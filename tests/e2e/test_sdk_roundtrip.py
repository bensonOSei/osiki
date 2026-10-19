"""The osiki-sdk running in-process against the real engine app."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from osiki_sdk import Osiki, OsikiGuard
from osiki_sdk.filters import to_sqlalchemy
from sqlalchemy import Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from tests.e2e import conftest as engine_conftest
from tests.e2e.conftest import API
from tests.e2e.conftest import app as engine_app

ENV = "dev"
ENV_HEADER = {"X-Osiki-Environment": ENV}
OWN_TEAM = {
    "op": "eq",
    "left": {"ref": "record.team_id"},
    "right": {"ref": "user.team_id"},
}
INVOICES = {
    "1": {"id": 1, "team_id": "t1"},
    "2": {"id": 2, "team_id": "t2"},
}


class Base(DeclarativeBase):
    pass


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[str] = mapped_column(String)


def _developer_app(osiki: Osiki) -> FastAPI:
    dev_app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @osiki.loader("invoice")
    async def load_invoice(invoice_id: str) -> dict[str, Any] | None:
        return INVOICES.get(invoice_id)

    @dev_app.get("/invoices/{invoice_id}")
    async def get_invoice(invoice_id: str, request: Request) -> dict[str, Any]:
        record: dict[str, Any] = request.state.osiki_record
        return record

    dev_app.add_middleware(OsikiGuard, osiki=osiki)
    return dev_app


class Flow:
    """Engine-side setup (admin API) plus calls into the developer's app."""

    def __init__(self, osiki: Osiki, dev_app: FastAPI) -> None:
        self.osiki = osiki
        self.dev_app = dev_app
        self.engine = httpx.AsyncClient(
            transport=httpx.ASGITransport(engine_app),
            base_url="http://engine",
            headers=ENV_HEADER,
        )
        self.dev = httpx.AsyncClient(
            transport=httpx.ASGITransport(dev_app),
            base_url="http://dev",
            headers={"x-user": "kofi", "x-tenant": "acme"},
        )
        self.user_id = ""
        self.role_id = ""

    async def post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        response = await self.engine.post(f"{API}{url}", json=body)
        assert response.status_code == 201, response.text
        data: dict[str, Any] = response.json()
        return data

    async def put(self, url: str, body: dict[str, Any] | None = None) -> None:
        response = await self.engine.put(f"{API}{url}", json=body)
        assert response.status_code in (200, 204), response.text

    async def seed(self) -> None:
        permission = await self.post(
            "/permissions", {"resource": "invoices", "action": "read"}
        )
        condition = await self.post(
            "/conditions",
            {"key": "own_team", "name": "Own team", "expression": OWN_TEAM},
        )
        role = await self.post(
            "/roles",
            {
                "name": "invoice-reader",
                "grants": [
                    {
                        "permission_id": permission["id"],
                        "condition_id": condition["id"],
                    }
                ],
            },
        )
        self.role_id = role["id"]
        await self.put("/tenants/acme", {"name": "Acme"})
        await self.put(
            "/users/by-external/kofi",
            {"name": "Kofi", "attributes": {"team_id": "t1"}},
        )
        user = (await self.engine.get(f"{API}/users", params={"page_size": 100})).json()
        self.user_id = user["items"][0]["id"]
        await self.put("/tenants/acme/members/kofi")
        await self.post(
            f"/users/{self.user_id}/roles",
            {
                "role_id": self.role_id,
                "assigned_by": "admin",
                "scope": {"tenant_id": "acme"},
            },
        )

    async def map_invoices(self) -> None:
        await self.put(
            "/endpoints/mapping",
            {
                "method": "GET",
                "path": "/invoices/{invoice_id}",
                "permission": "invoices:read",
                "record_type": "invoice",
                "record_id_param": "invoice_id",
            },
        )
        await self.osiki._store.poll_once()

    async def get_invoice(self, invoice_id: str) -> httpx.Response:
        return await self.dev.get(f"/invoices/{invoice_id}")

    async def close(self) -> None:
        await self.osiki.aclose()
        await self.engine.aclose()
        await self.dev.aclose()


@pytest.fixture
async def flow() -> AsyncIterator[Flow]:
    osiki = Osiki(
        base_url="http://engine",
        environment=ENV,
        transport=httpx.ASGITransport(engine_app),
        log_success_sample_rate=1.0,
        user_id=lambda request: request.headers.get("x-user"),
        tenant=lambda request: request.headers.get("x-tenant"),
    )
    flow = Flow(osiki, _developer_app(osiki))
    await flow.seed()
    yield flow
    await flow.close()


async def test_full_flow(flow: Flow) -> None:
    await flow.osiki.discover(flow.dev_app)

    listed = (await flow.engine.get(f"{API}/endpoints")).json()
    row = next(r for r in listed if r["path"] == "/invoices/{invoice_id}")
    assert row["method"] == "GET"
    assert row["mapping"] is None

    await flow.map_invoices()

    allowed = await flow.get_invoice("1")
    assert allowed.status_code == 200
    assert allowed.json() == INVOICES["1"]

    denied = await flow.get_invoice("2")
    assert denied.status_code == 403
    assert denied.json() == {"detail": "forbidden", "reason": "condition_failed"}


async def test_revocation_propagates_after_poll(flow: Flow) -> None:
    await flow.osiki.discover(flow.dev_app)
    await flow.map_invoices()
    assert (await flow.get_invoice("1")).status_code == 200

    revoked = await flow.engine.delete(
        f"{API}/users/{flow.user_id}/roles/{flow.role_id}",
        params={"tenant_id": "acme"},
    )
    assert revoked.status_code == 204
    await flow.osiki._store.poll_once()

    response = await flow.get_invoice("1")
    assert response.status_code == 403
    assert response.json() == {"detail": "forbidden", "reason": "no_permission"}


async def test_filter_roundtrip_sqlalchemy(flow: Flow) -> None:
    await flow.osiki.start()
    result = await flow.osiki.filter("kofi", "invoices", "read", tenant="acme")
    assert result.mode == "filter"

    sql_engine = create_engine("sqlite://")
    Base.metadata.create_all(sql_engine)
    with Session(sql_engine) as session:
        session.add_all(
            [
                Invoice(id=1, team_id="t1"),
                Invoice(id=2, team_id="t2"),
                Invoice(id=3, team_id="t1"),
            ]
        )
        session.commit()
        rows = session.scalars(
            select(Invoice).where(to_sqlalchemy(result, Invoice)).order_by(Invoice.id)
        ).all()

    assert [row.id for row in rows] == [1, 3]


async def test_decision_logs_reach_engine(flow: Flow) -> None:
    await flow.osiki.discover(flow.dev_app)
    await flow.map_invoices()
    assert (await flow.get_invoice("1")).status_code == 200
    assert (await flow.get_invoice("2")).status_code == 403

    await flow.osiki.aclose()

    logs = await engine_conftest._access_log_repos[ENV].get_by_user("kofi")
    assert logs
    assert {log.source for log in logs} == {"sdk"}
    assert {(log.resource, log.action, log.allowed) for log in logs} == {
        ("invoices", "read", True),
        ("invoices", "read", False),
    }
