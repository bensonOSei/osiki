# osiki-sdk

Python SDK for [Osiki](../../README.md). It checks every request locally
against a cached snapshot of your roles, endpoint map and rules, and it
translates rules into list filters for SQLAlchemy and Mongo.

## 1. Set up a dev environment first

Every environment starts with `unmapped = "deny"`: once the guard is in, any
route without a mapping answers `403 {"detail":"forbidden","reason":"unmapped"}`.
Retrofit an existing app on a **dev** environment that allows unmapped routes
(each one is logged once as a warning), and map routes as you go:

```
curl -X PUT "$OSIKI_URL/api/v1/settings" \
  -H "X-Osiki-Environment: dev" -H "Content-Type: application/json" \
  -d '{"unmapped":"allow"}'
```

Keep production on `deny`. Mark the routes that must work without a user as
public in code, so they work in every environment, mapped or not:

```python
OsikiConfig(..., public_routes=(("POST", "/auth/login"), ("GET", "/health")))
```

FastAPI's own `/docs`, `/docs/oauth2-redirect`, `/redoc` and `/openapi.json`
are discovered like any route. In a `deny` environment they answer 403 unless
you map them (as public) or list them in `public_routes`, or turn them off
(`FastAPI(docs_url=None, redoc_url=None, openapi_url=None)`).

## 2. Install

Until the package is on PyPI (M4), install from the repository:

```
pip install "osiki-sdk @ git+https://github.com/bensonOSei/osiki.git#subdirectory=sdks/python"
pip install "osiki-sdk[sqlalchemy] @ git+https://github.com/bensonOSei/osiki.git#subdirectory=sdks/python"
```

or, from a checkout, `pip install -e sdks/python` (with Poetry:
`poetry add --editable ../osiki/sdks/python`).

## 3. The two lines

```python
from osiki_sdk import Osiki, OsikiGuard

osiki = Osiki(
    base_url=OSIKI_URL,
    api_key=OSIKI_KEY,
    environment="dev",
    user_id=lambda req: decode_access_token(req.headers.get("authorization")),
)
app.add_middleware(OsikiGuard, osiki=osiki)
```

On the first request the guard loads the snapshot, starts polling for changes
and reports your routes to Osiki in the background, where they show up as
unmapped until you map them. In the dashboard (or with
`PUT /api/v1/endpoints/mapping`) map each route, by its template, to a
permission, or mark it public:

```json
{"method": "DELETE", "path": "/invoices/{invoice_id}",
 "permission": "invoices:delete",
 "record_type": "invoice", "record_id_param": "invoice_id"}
```

Requests are matched by route template, never by raw path: `/invoices/42`
matches `DELETE /invoices/{invoice_id}`. Included routers match with their
full prefixed template. `HEAD` follows the `GET` mapping. A path no route
takes reaches the app, which answers 404, 405 or a trailing-slash redirect
(the redirected request is checked again). WebSocket and lifespan traffic is
not guarded.

`OPTIONS` gets no special treatment. A CORS preflight to an ordinary route
matches no route, so it still reaches the app (and an outer `CORSMiddleware`
answers preflights before the guard sees them). A route that really handles
`OPTIONS` (`@app.options`, `api_route(methods=[..., "OPTIONS"])`, an ASGI
endpoint or a mount) is unmapped, because a mapping cannot hold `OPTIONS`. In a
`deny` environment it answers 403 unless you list `("OPTIONS", template)` in
`public_routes`.

Mounts are opaque: `app.mount(...)`, sub-apps, `Host` routes, ASGI-class
endpoints, FastAPI `frontend()` routes and a custom router `default` app. The guard cannot see their routes,
so it always treats them as unmapped; in a `deny` environment they answer 403.

Close Osiki on shutdown so pending decision logs are sent:

```python
@asynccontextmanager
async def lifespan(app):
    yield
    await osiki.aclose()
```

## 4. The user resolver is the trust boundary

`user_id` returns the caller's user id (a non-empty `str`) or `None`, and may
be sync or async. `None`, an empty string, a non-string or an exception gives
`401 {"detail":"unauthenticated"}`. Whatever it returns is trusted, so it must
**verify** the credential, not just read it.

FastAPI dependencies (`Depends(get_current_user)`) run **after** middleware,
so `request.state.user` does not exist yet when the guard runs. Decode and
verify the bearer token in the resolver with your app's own JWT helper:

```python
def resolve_user(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    claims = decode_access_token(token)  # verifies signature and expiry
    return str(claims["sub"])
```

The resolver gets a `Request` whose body cannot be read; use headers, cookies
and the path.

### Ordering with an auth middleware

If your app authenticates in a *middleware* that sets `request.state.user`,
the guard must run after it. `add_middleware` wraps outermost-last, so add the
guard **before** the auth middleware:

```python
app.add_middleware(OsikiGuard, osiki=osiki)  # inner: runs second
app.add_middleware(AuthMiddleware)           # outer: runs first
```

The guard decides on the path and method it sees. A middleware between the
guard and the router (added before the guard) must never rewrite
`scope["path"]` or `scope["method"]`, or the app could run a route the guard
did not check.

## 5. Tenants

When a user can belong to several businesses, pass a tenant resolver that
returns the active tenant id per request (a header, a path segment, a
subdomain). It may be sync or async:

```python
osiki = Osiki(..., user_id=resolve_user, tenant=lambda req: req.headers.get("x-tenant"))
```

A falsy result means "no tenant", and a raise gives 401. Membership comes from
Osiki's own records (section 9), never from the token: a user who is not a
member of the tenant is denied with `reason: "not_tenant_member"`.

## 6. Record checks and loaders

For a mapping with a `record_type`, the guard loads the record through the
loader you register once per type. It passes the path parameter named by
`record_id_param`, always as a `str`:

```python
@osiki.loader("invoice")
async def load_invoice(invoice_id: str) -> Invoice | None:
    return await db.get(Invoice, int(invoice_id))
```

The guard decides **before** it loads. A caller with no matching grant, or
unknown to Osiki, is denied (and logged) without the loader running, so they
get the same 403 for an id that exists and one that does not. The loader runs
only when the caller holds a matching grant: an unconditional grant still loads
the record (for the handler), and a conditional one is decided again against
it.

- `None` gives `404 {"detail":"not found"}`.
- An exception gives `503 {"detail":"authorization unavailable"}`.
- A missing loader gives `503 {"detail":"authorization misconfigured"}`,
  logged once.

The record may be a dict, a pydantic model, a dataclass or a SQLAlchemy row.
It is converted with `to_record`, so rules over ids still match:

- `datetime` and `date` become ISO strings;
- `UUID` and `ObjectId` become strings;
- `Decimal` becomes a float, and an enum its value.

The handler gets the same object, so the record is loaded once:

```python
@app.delete("/invoices/{invoice_id}")
async def delete_invoice(invoice_id: int, request: Request):
    invoice = request.state.osiki_record
```

## 7. `check` and `filter`

Outside the guard (background jobs, per-field checks), call Osiki directly:

```python
await osiki.start()  # once, e.g. in your lifespan; the guard does it for you
decision = await osiki.check("kofi", "invoices", "update", tenant="acme", record=invoice)
if not decision.allowed:
    print(decision.denial_reason)

result = await osiki.filter("kofi", "invoices", "read", tenant="acme")
```

Before the first snapshot has loaded, both raise `OsikiUnavailable`. A cold
bundle fetch can also raise `EngineUnavailable` (engine down or 5xx) or
`EngineError` (an unexpected response). Treat all three as "deny".

## 8. List filters

`filter` returns a `FilterResult` whose `mode` is `"all"`, `"none"` or
`"filter"`. Translate it for your database:

```python
from osiki_sdk.filters import to_mongo, to_sqlalchemy

where = to_sqlalchemy(result, Invoice)  # a WHERE clause; needs the [sqlalchemy] extra
rows = await session.scalars(select(Invoice).where(where))

query = to_mongo(result)  # {} for everything, None for nothing
docs = [] if query is None else await db.invoices.find(query).to_list(None)
```

Both keep the rule's type guard: a string never matches a numeric field, and a
boolean never matches a number.

SQL string comparisons follow your database's collation. MySQL `_ci`
collations ignore case and Postgres follows its locale, while the engine
compares case-sensitively by code point. So `check` and a SQL filter can
disagree on case for string fields.

## 9. Sync users and tenants

Osiki does not do authentication, so tell it who exists:

```python
await osiki.users.upsert("kofi", name="Kofi", email="kofi@example.com",
                         attributes={"team_id": "t1"})
await osiki.tenants.upsert("acme", name="Acme Ltd", attributes={"plan": "pro"})
await osiki.tenants.add_member("acme", "kofi")
await osiki.tenants.remove_member("acme", "kofi")  # True when it was a member
```

`tenants.upsert(...)` without `attributes` **replaces** the tenant's stored
attributes with `{}`, so pass them every time. Each call drops the cached
bundles it affects. Other processes pick up role, membership and user changes
on their next poll, within `poll_interval` seconds.

## 10. Failure modes

| Situation | Answer |
| --- | --- |
| No snapshot has ever loaded (cold start, engine down): a write | `503 authorization unavailable` |
| No snapshot has ever loaded: `GET`/`HEAD` | `read_on_unavailable`: `"deny"` (503, the default) or `"allow"` |
| Engine down after a snapshot loaded | keeps deciding from the cached snapshot and bundles |
| Engine down and the user's bundle is not cached | the route's `on_unavailable` if set; else `read_on_unavailable` for `GET`/`HEAD`; else `503 authorization unavailable`. An allow calls the app without a decision log |
| The engine answers the bundle fetch unexpectedly (`EngineError`) | `503 authorization unavailable` |
| Unmapped route or mount | `deny` env: `403 unmapped`; `allow` env: passes, one warning per route |
| No user, or the resolver raises | `401 unauthenticated` |
| User unknown to Osiki | `403 unknown_user` |
| Denied by roles or rules | `403` with `reason` (`no_permission`, `not_tenant_member`, `condition_failed`, `record_required`) |
| Any error inside the guard, including after `aclose()` | `503 authorization unavailable`; the app is never called |

When in doubt, the guard denies. Decisions run locally in well under 1 ms,
excluding your loader's query. Decision logs are queued and sent in the
background, never on the request path. Every denial is logged; successes are
sampled.

## 11. Configuration

Use `Osiki(OsikiConfig(...), user_id=...)` or pass the fields to `Osiki`
directly:

| Field | Default | Meaning |
| --- | --- | --- |
| `base_url` | required | The Osiki engine URL. |
| `environment` | `"default"` | Sent as `X-Osiki-Environment`. |
| `api_key` | `None` | Sent as `Authorization: Bearer ...` when set. |
| `poll_interval` | `2.0` | Seconds between version polls; revocations apply within this. |
| `bundle_ttl` | `60.0` | Seconds a user's bundle stays cached. |
| `bundle_cache_size` | `10000` | Most bundles cached (LRU). |
| `read_on_unavailable` | `"deny"` | `GET`/`HEAD` behaviour when a check cannot be decided (no snapshot yet, or engine down and the bundle not cached). |
| `public_routes` | `()` | `(METHOD, template)` pairs that skip the guard in every environment. |
| `log_success_sample_rate` | `0.1` | Share of allowed decisions logged; denials always are. |
| `log_flush_interval` | `2.0` | Seconds between decision-log sends. |
| `log_batch_size` | `100` | Pending entries that trigger an early send. |
| `request_timeout` | `2.0` | Seconds per engine request. |

A mapping can also set `on_unavailable` (`"deny"` or `"allow"`). It overrides
`read_on_unavailable` and the write default when the engine is down and the
caller's bundle is not cached. Before the first snapshot loads no mapping is
known, so the defaults above decide.

## Development

```
poetry install
poetry run pytest --cov=osiki_sdk
poetry run mypy src && poetry run ruff check . && poetry run black --check .
```

`osiki_sdk/_decision` is a vendored copy of the engine's pure decision package,
generated by `scripts/sync_sdk_decision.py`; never edit it by hand.
