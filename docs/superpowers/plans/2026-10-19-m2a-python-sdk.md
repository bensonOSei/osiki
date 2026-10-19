# M2a — Python SDK and Endpoint Map: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A FastAPI developer adds Osiki with about two lines. Every route is then checked locally against the cached snapshot, and endpoints can be mapped to permissions from the engine. This includes record-level rules, list filters for SQLAlchemy and Mongo, user and tenant sync, and failure modes that deny safely.

**Architecture:** Changes on the engine side:
- an endpoint map (discovered routes plus developer mappings) and per-environment settings, both shipped inside the snapshot;
- an `assignments_version` counter, so SDKs learn about role, membership and user changes within seconds by polling.

The SDK lives in this repo at `sdks/python` and is published as `osiki-sdk`, imported as `osiki_sdk`. It carries a byte-identical copy of `osiki/decision/`, which CI keeps in sync, and it decides locally. Its pure ASGI middleware does the following:
- matches each request to its route template;
- resolves the user and tenant;
- loads the record through a registered loader;
- calls `decide`;
- sends decision logs in background batches.

**Tech Stack:** Python 3.11+ (SDK), Python 3.13 (engine), httpx, pydantic 2, Starlette/FastAPI, SQLAlchemy 2 (optional extra), pytest + pytest-asyncio, Poetry 2.3.

**Spec:** `docs/superpowers/specs/2026-10-18-osiki-cloud-design.md`. Relevant sections:
- §3 escape hatch
- §5.2 guard
- §5.3 unreachable
- §5.4 record checks
- §5.5 sync
- §5.10 HTTP API
- §6 performance

Prior work: `docs/superpowers/plans/2026-10-18-m1-engine-ready-for-cloud.md` and `conformance/README.md`.

## Global Constraints

- **Engine (`osiki/`):**
  - Python `>=3.13,<3.14`, mypy strict.
  - ruff `E F I N W UP`, black 88.
  - Coverage `fail_under = 100`.
  - Every `Base*Repository` method is mirrored on its `Mock*Repository`; every new model gets a `make_*` factory.
  - Every repository is environment-bound (`__init__(environment_id)`).
  - CI runs `mypy .` over the whole repo.
- **`osiki/decision/` must stay Python 3.11-compatible from now on:**
  - no `type X = …` statements and no PEP 695 generics;
  - use `typing.TypeAlias` with `# noqa: UP040`;
  - pure: stdlib plus pydantic only.
- **SDK (`sdks/python/`):**
  - Python `>=3.11`, tested on 3.11 and 3.13.
  - mypy strict, ruff and black as the engine.
  - Coverage `fail_under = 100` on `osiki_sdk`, excluding `osiki_sdk/_decision/`, which is covered by the engine.
  - Runtime deps: `httpx`, `pydantic>=2`, `starlette`.
  - Optional extra `sqlalchemy` (`sqlalchemy>=2`).
  - No dependency on the engine package.
- `sdks/python/src/osiki_sdk/_decision/` is a verbatim copy of `osiki/decision/`. It is produced only by `scripts/sync_sdk_decision.py`, and CI fails on drift.
- Spec §6 targets:
  - a local check takes `< 1 ms`, excluding the developer's loader query;
  - revocations and config changes apply within seconds;
  - logging never sits on the request path.
- Spec §5.3: writes fail closed by default; reads are configurable. "When in doubt, deny."
- The SDK sends `Authorization: Bearer <api_key>` when an api_key is configured, plus `X-Osiki-Environment`. The engine ignores the bearer token; the M2b cloud gateway will check it.
- **The user resolver is the trust boundary.** Poully and Elite Frames authenticate through FastAPI dependencies, which run after middleware, so `request.state.user` doesn't exist when the guard runs. Resolvers must verify the bearer token themselves using the app's own JWT decode helper. Apps with an auth *middleware* add `OsikiGuard` before it (`add_middleware` wraps outermost-last, so the guard ends up inner).
- **Deviation from the spec's builder's call** (§5.2: deny unmapped in prod, allow+warn in dev): environments are just strings, so the engine can't tell dev from prod. Every environment defaults to `unmapped="deny"`; developers set `PUT /settings {"unmapped":"allow"}` on dev environments. The SDK README opens with this step.
- One PR for all of M2a.

## Review Focus

1. **Engine unreachable at cold start** (no snapshot has ever loaded): writes get 503, reads follow `read_on_unavailable` (default deny). The app never sees a 500 or an allow. Pinned in Task S5.
2. **Revocation while a bundle is cached:** after the next poll tick, the same request is denied. Pinned in Task S6.
3. **Requests are matched by route template, not raw path:** `/invoices/42` matches `GET /invoices/{invoice_id}`. A mounted sub-app is never silently allowed. `HEAD` follows GET and `OPTIONS` passes through, never a 500. Pinned in Task S5.
4. **A loader that returns `None`, raises, or returns non-JSON values** (datetime, ObjectId, UUID, Decimal): `None` gives 404, an exception gives 503, and values are converted by `to_record` so rules over ids still match. Pinned in Task S5.
5. **Filter translation keeps the leaf `type` guard:** a string never matches a numeric column or field, and a boolean never matches a number, in both translators. Pinned in Task S4.

---

## File Structure

```
osiki/decision/models.py, rules.py      MOD  TypeAlias; Snapshot endpoints+settings; DenialReason "unknown_user"
osiki/models/endpoint.py                NEW  DiscoveredEndpoint, EndpointMapping
osiki/models/environment_state.py       MOD  assignments_version, unmapped_policy
osiki/repositories/endpoints/           NEW  endpoint repo (discovered + mappings)
osiki/repositories/environment_state/   MOD  assignments version, settings
osiki/repositories/{users,tenants,tenant_members,user_roles,group_roles,user_groups,groups}/mongodb_*.py
                                        MOD  bump assignments_version on writes
osiki/services/snapshot_builder/        MOD  render endpoints + settings
osiki/api/routes/endpoints.py           NEW  /endpoints, /endpoints/discovered, /endpoints/mapping
osiki/api/routes/settings.py            NEW  GET/PUT /settings
osiki/api/routes/snapshot.py            MOD  /snapshot/version returns both versions
scripts/sync_sdk_decision.py            NEW  copy / --check
sdks/python/
  pyproject.toml, README.md
  src/osiki_sdk/
    __init__.py            public API
    _decision/             vendored copy (generated)
    config.py              OsikiConfig
    client.py              EngineClient (HTTP), EngineUnavailable, EngineError
    records.py             to_record
    store.py               PolicyStore (snapshot, bundles, version poller)
    osiki.py               Osiki facade: check, filter, loaders, sync, start/discover/aclose
    filters/{__init__,sqlalchemy,mongo}.py   to_sqlalchemy, to_mongo
    routes.py              match_route, list_routes
    logs.py                DecisionLogBatcher
    guard.py               OsikiGuard ASGI middleware
  tests/
.github/workflows/sdk.yml               NEW  SDK CI (3.11, 3.13) + drift check
tests/e2e/test_sdk_roundtrip.py         NEW  SDK against the in-process engine
```

---

## Phase E — Engine

### Task E1: Python 3.11-compatible decision core, snapshot fields, assignments version

**Files:**
- Modify:
  - `osiki/decision/models.py`, `osiki/decision/rules.py`, `conformance/README.md`
  - `osiki/models/environment_state.py`, `osiki/repositories/environment_state/*`
  - the Mongo repos for users, tenants, tenant_members, user_roles, group_roles, user_groups and groups
  - `osiki/services/snapshot_builder/snapshot_builder.py`, `osiki/api/routes/snapshot.py`
  - mocks
- Create: `tests/unit/decision/test_py311_compat.py`

**Interfaces:**
- Produces, in `osiki/decision/models.py` (pure, 3.11-compatible):
  - `EndpointEntry(_Frozen)`:
    - `method: str` (upper-case)
    - `path: str` (route template exactly as the framework declares it, e.g. `"/api/v1/invoices/{invoice_id}"` or `"/files/{name:path}"`)
    - `permission: str | None` (`"res:act"`; `None` only when `public`)
    - `record_type: str | None = None`
    - `record_id_param: str | None = None`
    - `public: bool = False`
    - `on_unavailable: Literal["deny","allow"] | None = None` (`None` means the SDK default)
  - `EnvironmentSettings(_Frozen)`: `unmapped: Literal["deny","allow"] = "deny"`.
  - `Snapshot` gains `endpoints: list[EndpointEntry] = []` and `settings: EnvironmentSettings = EnvironmentSettings()`. Both have defaults, so existing fixtures stay valid.
  - `Via`, `DenialReason` (and `FilterNode` in `rules.py`) become `X: TypeAlias = …  # noqa: UP040`.
  - `DenialReason` gains `"unknown_user"`. `decide` never returns it; callers return it when the bundle is `None`, matching the server's `/authorization/check`. Document this in the docstring and `conformance/README.md`.
- Produces, in the engine:
  - `EnvironmentState` gains `assignments_version: int = 0` and `unmapped_policy: Literal["deny","allow"] = "deny"`.
  - `BaseEnvironmentStateRepository` gains:
    - `get_assignments_version() -> int`
    - `bump_assignments_version() -> int` (atomic `$inc` upsert)
    - `get_settings() -> EnvironmentSettings`
  - The snapshot builder renders `settings` from the state repo. It renders `endpoints=[]` until E2.
  - `GET /snapshot/version` → `{"version": int, "assignments_version": int}`.
  - The assignments version is bumped after every successful write in:
    - users: upsert, create, update, deactivate
    - tenants: upsert
    - tenant_members: add, remove
    - user_roles: create, revoke
    - group_roles: create, revoke
    - user_groups: create, remove
    - groups: deactivate, reactivate

    A failed write does not bump.

- [ ] **Step 1: Write failing tests:**
  - `test_decision_package_is_311_compatible`: parse every `osiki/decision/*.py` with `ast.parse(src, feature_version=(3, 11))`, and assert no `ast.TypeAlias` node exists.
  - `test_assignments_version_bumps_on_every_assignment_write`: parametrized over each write above; each strictly increases, and a failed write doesn't bump.
  - `test_snapshot_version_endpoint_returns_both`.
  - `test_snapshot_includes_default_settings`: `settings == {"unmapped":"deny"}` and `endpoints == []`.
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite and checks.** `poetry run pytest --cov=osiki` → 100%; `make lint`; `poetry run mypy .` clean; conformance green.
- [ ] **Step 5: Commit.** `git commit -m "feat: keep decision core 3.11-compatible and add assignments version"`

### Task E2: Endpoint map and environment settings

**Files:**
- Create: `osiki/models/endpoint.py`, `osiki/repositories/endpoints/{__init__,base_endpoint_repository,mongodb_endpoint_repository}.py`, `osiki/schemas/endpoint.py`, `osiki/api/routes/endpoints.py`, `osiki/api/routes/settings.py`, `tests/e2e/test_endpoints.py`, `tests/e2e/test_settings.py`, `tests/integration/repositories/test_endpoint_repository.py`
- Modify: `osiki/repositories/environment_state/*`, `osiki/services/snapshot_builder/snapshot_builder.py`, `osiki/api/dependencies.py`, `osiki/main.py`, `osiki/configs/database.py`, mocks, factories and conftests

**Interfaces:**
- Consumes: `EndpointEntry`, `EnvironmentSettings` and the state repo (E1).
- Produces:
  - `DiscoveredEndpoint(Document, EnvironmentMixin)`: `method`, `path`, `first_seen: float`, `last_seen: float`; unique `(environment_id, method, path)`.
  - `EndpointMapping(Document, EnvironmentMixin, TimestampMixin)`: the `EndpointEntry` fields; unique `(environment_id, method, path)`.
  - `BaseEndpointRepository(environment_id, state)`:
    - `record_discovered(endpoints: list[tuple[str, str]], now: float) -> int` (upsert; sets `last_seen`)
    - `list_discovered() -> list[DiscoveredEndpoint]`
    - `upsert_mapping(entry: EndpointEntry) -> EndpointMapping` (bumps config)
    - `delete_mapping(method: str, path: str) -> bool` (bumps config on success)
    - `list_mappings() -> list[EndpointMapping]`
  - `BaseEnvironmentStateRepository.update_settings(settings: EnvironmentSettings) -> EnvironmentSettings` (bumps config).
  - The snapshot builder renders mappings sorted by `(path, method)`.
- Routes:
  - `POST /endpoints/discovered` with body `{"endpoints": [{"method","path"}]}` (1–1000 items) → 202 `{"recorded": n}`.
  - `GET /endpoints` → `list[EndpointStatusRead{method, path, mapping: EndpointEntry | null, last_seen: float | null}]`. This is the union of discovered and mapped endpoints, sorted by `(path, method)`.
  - `PUT /endpoints/mapping` with body `EndpointEntry` → 200 `EndpointEntry`.
  - `DELETE /endpoints/mapping?method=&path=` → 204, or 404 if absent.
  - `GET /settings` and `PUT /settings` → `EnvironmentSettings`.
- Validation (422):
  - `method` must be one of GET, POST, PUT, PATCH, DELETE;
  - `path` must start with `/`;
  - `permission` must match `^[^:]+:[^:]+$`;
  - `public=False` requires `permission`;
  - `record_type` and `record_id_param` must be set together;
  - `record_id_param` must appear in `path` as `{name}` or `{name:<converter>}`;
  - `record_type` slug `^[a-z][a-z0-9_]{0,62}$`.

- [ ] **Step 1: Write failing tests:**
  - `test_snapshot_includes_mappings_and_settings`: `PUT /endpoints/mapping` with `{"method":"DELETE","path":"/invoices/{id}","permission":"invoices:delete","record_type":"invoice","record_id_param":"id"}`, then `GET /snapshot` → `endpoints[0]` equals the body (with defaults filled in).
  - `test_mapping_write_bumps_config_version`, `test_settings_write_bumps_config_version`.
  - `test_discovered_then_listed_as_unmapped`.
  - `test_mapping_validation_422`, parametrized: missing permission when not public; `record_id_param` absent from the path; bad method; `"a:b:c"` permission.
  - `test_record_id_param_with_converter_accepted` (`/invoices/{id:int}`).
  - `test_delete_mapping_404`.
  - `test_settings_roundtrip`.
  - `test_endpoints_env_isolated`.
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite and checks** (as in E1).
- [ ] **Step 5: Commit.** `git commit -m "feat: add endpoint map and environment settings to the snapshot"`

---

## Phase S — SDK

### Task S1: SDK package, vendored decision core, CI

**Files:**
- Create:
  - `scripts/sync_sdk_decision.py`, `tests/unit/test_sync_sdk_decision.py`
  - `sdks/python/{pyproject.toml,README.md}`
  - `sdks/python/src/osiki_sdk/__init__.py`
  - `sdks/python/src/osiki_sdk/_decision/` (generated)
  - `sdks/python/tests/test_conformance.py`
  - `.github/workflows/sdk.yml`
- Modify: `.github/workflows/ci.yml` (drift-check step), root `Makefile` (`sdk-sync`, `sdk-test`)

**Interfaces:**
- `scripts/sync_sdk_decision.py`:
  - `main(argv: list[str] | None = None) -> int`, with `--source` (default `osiki/decision`), `--dest` (default `sdks/python/src/osiki_sdk/_decision`) and `--check`.
  - It copies `*.py` byte-for-byte and removes stale `.py` files in the destination.
  - `--check` returns 1 and prints each differing, missing or stale file name.
- `sdks/python/pyproject.toml`:
  - Poetry, name `osiki-sdk`, version `0.1.0`, `packages = [{include = "osiki_sdk", from = "src"}]`, python `>=3.11`;
  - deps `httpx>=0.27`, `pydantic>=2.6`, `starlette>=0.37`;
  - extra `sqlalchemy = ["sqlalchemy>=2"]`;
  - dev: pytest, pytest-asyncio, pytest-cov, mypy, ruff, black, fastapi, sqlalchemy, mongomock-motor;
  - coverage `omit = ["src/osiki_sdk/_decision/*"]`, `fail_under = 100`.
- `sdks/python/tests/test_conformance.py` parametrizes over the repo's `conformance/{decisions,filters}/*.json` (located relative to the test file) and runs `osiki_sdk._decision`'s `decide`/`list_filter`. It is as strict as the engine runner: exact keys, full model equality.
- `.github/workflows/sdk.yml` runs on PRs touching `sdks/**`, `osiki/decision/**`, `conformance/**` or `scripts/sync_sdk_decision.py`. Its matrix is Python 3.11 and 3.13, and it runs:
  - `python scripts/sync_sdk_decision.py --check`
  - in `sdks/python`: `poetry install`, `black --check .`, `ruff check .`, `mypy src` and `pytest --cov=osiki_sdk`

- [ ] **Step 1: Write failing tests** (`tests/unit/test_sync_sdk_decision.py`, using `tmp_path`):
  - `test_check_passes_when_identical`
  - `test_check_fails_and_names_file_on_drift`
  - `test_sync_removes_stale_files`
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Implement** the script, run it to generate `_decision/`, then create the package skeleton, conformance runner, workflow and Makefile targets.
- [ ] **Step 4: Verify.**
  - The root tests pass at 100%.
  - `python scripts/sync_sdk_decision.py --check` exits 0.
  - In `sdks/python`: `poetry install && poetry run pytest` passes every conformance case.
  - Also run under Python 3.11 if installed (`poetry env use 3.11`); otherwise the report says CI covers it.
- [ ] **Step 5: Commit.** `git commit -m "feat: scaffold osiki-sdk with vendored decision core and drift check"`

### Task S2: Engine HTTP client and record conversion

**Files:**
- Create: `sdks/python/src/osiki_sdk/{config.py,client.py,records.py}`, `sdks/python/tests/{test_client.py,test_records.py}`

**Interfaces:**
- `@dataclass(frozen=True) class OsikiConfig` with fields:
  - `base_url: str`
  - `environment: str = "default"`
  - `api_key: str | None = None`
  - `poll_interval: float = 2.0`
  - `bundle_ttl: float = 60.0`
  - `bundle_cache_size: int = 10_000`
  - `read_on_unavailable: Literal["deny","allow"] = "deny"`
  - `public_routes: tuple[tuple[str, str], ...] = ()`: `(METHOD, template)` pairs that are public in code (spec §5.2), e.g. `(("GET","/health"),("POST","/auth/login"))`
  - `log_success_sample_rate: float = 0.1`
  - `log_flush_interval: float = 2.0`
  - `log_batch_size: int = 100`
  - `request_timeout: float = 2.0`
- `class EngineClient(config: OsikiConfig, transport: httpx.AsyncBaseTransport | None = None)`. Every call sends `X-Osiki-Environment`, plus `Authorization: Bearer <api_key>` when set. Path segments are URL-encoded. Methods:
  - `get_snapshot(etag: str | None) -> tuple[Snapshot | None, str | None]`: `(None, etag)` on 304
  - `get_versions() -> tuple[int, int]`: config, assignments
  - `get_bundle(user_id: str) -> UserBundle | None`: 404 → `None`
  - `report_endpoints(endpoints: list[tuple[str, str]]) -> None`: chunks of 1000
  - `send_access_logs(entries: list[dict[str, Any]]) -> None`: chunks of 500
  - `upsert_user(user_id, *, name=None, email=None, attributes=None) -> None`
  - `upsert_tenant(tenant_id, *, name, attributes=None) -> None`
  - `add_member(tenant_id, user_id) -> None`
  - `remove_member(tenant_id, user_id) -> bool`
  - `aclose() -> None`
- Errors:
  - transport errors and 5xx → `EngineUnavailable(Exception)`;
  - other non-2xx (except the 304/404 cases above) → `EngineError(status: int, body: Any)`.
- `to_record(obj: Any) -> dict[str, Any]` accepts a Mapping, a pydantic model (`model_dump()`), a dataclass, or a SQLAlchemy mapped instance (column attributes via `sqlalchemy.inspect`, only if importable). It converts recursively:
  - `uuid.UUID`, or any value whose class is named `ObjectId` → `str`
  - `datetime`/`date` → `isoformat()`
  - `Decimal` → `float`
  - `Enum` → `.value`
  - set or tuple → list
  - any other non-JSON value → `str`

- [ ] **Step 1: Write failing tests** using `httpx.MockTransport`:
  - `test_snapshot_304_returns_none_with_etag`
  - `test_headers_sent` (bearer only when `api_key` is set)
  - `test_bundle_404_none`
  - `test_5xx_and_connect_error_raise_unavailable`
  - `test_4xx_raises_engine_error`
  - `test_report_endpoints_chunks_1000`
  - `test_access_logs_chunks_500`
  - `test_user_id_url_encoded`: `"a/b"` → `/api/v1/users/by-external/a%2Fb/bundle`
  - `test_to_record_converts_objectid_uuid_datetime_decimal_enum`
  - `test_to_record_pydantic_and_dataclass`
  - `test_to_record_sqlalchemy_model`
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `poetry run pytest --cov=osiki_sdk` in `sdks/python` → 100%.
- [ ] **Step 5: Commit.** `git commit -m "feat(sdk): add engine client, config and record conversion"`

### Task S3: Policy store and the `Osiki` facade

**Files:**
- Create: `sdks/python/src/osiki_sdk/{store.py,osiki.py}`, `sdks/python/tests/{test_store.py,test_osiki.py}`
- Modify: `sdks/python/src/osiki_sdk/__init__.py`

**Interfaces:**
- `class PolicyStore(client: EngineClient, config: OsikiConfig, clock: Callable[[], float] = time.monotonic)`:
  - `snapshot: Snapshot | None` and `available: bool` (a snapshot has loaded at least once)
  - `async refresh_snapshot() -> None`: ETag-aware
  - `async get_bundle(user_id: str) -> UserBundle | None`: an LRU of `bundle_cache_size`; an entry expires after `bundle_ttl`; `None` results are cached too
  - `invalidate_user(user_id: str) -> None`, `clear_bundles() -> None`
  - `async poll_once() -> None`: reads both versions. A changed config version → `refresh_snapshot()`; a changed assignments version → `clear_bundles()`.
  - `async run_poller() -> None`: loops `poll_once` every `poll_interval`. Errors are logged and swallowed; the last good snapshot is kept.
- `class Osiki(config: OsikiConfig | None = None, *, user_id: UserResolver, tenant: TenantResolver | None = None, transport: httpx.AsyncBaseTransport | None = None, **config_kwargs)`, where `config_kwargs` builds an `OsikiConfig` when `config` is None:
  - `UserResolver = Callable[[Request], str | None | Awaitable[str | None]]` (Starlette `Request`); `TenantResolver` is the same shape.
  - `loader(record_type: str) -> Callable[[LoaderFn], LoaderFn]`, with `LoaderFn = Callable[[str], Awaitable[Any | None]]`. A duplicate registration → `ValueError`. Also `get_loader(record_type) -> LoaderFn | None`.
  - `async start() -> None`: idempotent and concurrency-safe (`asyncio.Lock` plus a flag). It does the first `refresh_snapshot` (failure is logged and leaves the store unavailable), then starts exactly one poller task and one log batcher.
  - `async discover(app: Starlette) -> None`: idempotent per app. It reports `routes.list_routes(app)` via `client.report_endpoints`; a failure is logged and the next call retries.
  - `async check(user_id: str, resource: str, action: str, *, tenant: str | None = None, record: Any | None = None) -> Decision`: the spec §3 escape hatch. It runs locally on the cached snapshot and bundle, converts `record` with `to_record`, and passes `now=time.time()`. A missing bundle → `Decision(allowed=False, denial_reason="unknown_user")`. If the store is unavailable → raise `OsikiUnavailable`.
  - `async filter(user_id: str, resource: str, action: str, *, tenant: str | None = None) -> FilterResult`: a missing bundle → `FilterResult(mode="none")`.
  - `users.upsert(id, *, name=None, email=None, attributes=None)`, `tenants.upsert(id, *, name, attributes=None)`, `tenants.add_member(tenant_id, user_id)`, `tenants.remove_member(tenant_id, user_id)`: call the client, then `invalidate_user` for the affected user.
  - `async aclose() -> None`: stop the poller, flush and stop the batcher, close the client. `started: bool`.
- `osiki_sdk.__init__` exports `Osiki`, `OsikiConfig`, `Decision`, `FilterResult`, `to_record`, `OsikiUnavailable`, `EngineError`, `EngineUnavailable`.

- [ ] **Step 1: Write failing tests** (a fake in-memory client with the `EngineClient` methods, plus a manual clock):
  - `test_check_allows_via_cached_snapshot_and_bundle`: the second check makes no network call.
  - `test_assignments_version_change_clears_bundles`
  - `test_config_version_change_refreshes_snapshot`
  - `test_bundle_ttl_expiry_refetches`
  - `test_lru_evicts_oldest`
  - `test_poll_error_keeps_last_snapshot`
  - `test_check_unavailable_before_first_snapshot_raises`
  - `test_check_unknown_user_returns_unknown_user`
  - `test_check_converts_record_with_to_record`
  - `test_filter_returns_typed_filter`
  - `test_sync_wrappers_call_client_and_invalidate_user`
  - `test_duplicate_loader_raises`
  - `test_start_is_idempotent_under_concurrency`: 50 concurrent `start()` calls → exactly one poller.
  - `test_discover_idempotent_and_retries_after_failure`
  - `test_check_latency_under_1ms`: 1,000 warm checks, median under 1 ms. Mark it `perf`; if CI noise is an issue, assert a 2 ms median and print the figure.
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the SDK suite** → 100%.
- [ ] **Step 5: Commit.** `git commit -m "feat(sdk): add policy store with version polling and local check/filter"`

### Task S4: List-filter translators

**Files:**
- Create: `sdks/python/src/osiki_sdk/filters/{__init__,sqlalchemy,mongo}.py`, `sdks/python/tests/{test_filter_sqlalchemy.py,test_filter_mongo.py}`

**Interfaces:**
- Leaf contract (`conformance/README.md`): a leaf matches only when the field is present, non-null, of the leaf's `type` class (a boolean is never a number), and satisfies op and value. Ops: `eq ne lt lte gt gte in nin`.
- `to_mongo(result: FilterResult) -> dict[str, Any] | None`:
  - `mode="all"` → `{}`;
  - `mode="none"` → `None` (the caller returns nothing);
  - `"filter"`: `and`/`or` become `$and`/`$or`; a leaf becomes `{field: {"$type": T, "$<op>": value}}`, where:
    - T is `"string"`, `"number"` or `"bool"`. `"number"` covers int, long, double and decimal, which matches `to_record` turning `Decimal` into a number; it was verified under mongomock to exclude booleans.
    - Ops map to `$eq $ne $lt $lte $gt $gte $in $nin`.
- `to_sqlalchemy(result: FilterResult, model: type[Any]) -> ColumnElement[bool]`:
  - `"all"` → `true()`; `"none"` → `false()`;
  - a leaf becomes `false()` when:
    - the model has no such attribute;
    - the column's `type.python_type` raises `NotImplementedError`;
    - the column's class doesn't match the leaf's type: `str` for string; `int`/`float`/`Decimal` (but not `bool`) for number; `bool` for boolean.
  - Otherwise a leaf is `and_(col.is_not(None), <op>)`, using `in_`/`not_in` for `in`/`nin`.
- `osiki_sdk.filters` exports both. The SQLAlchemy import is lazy, and a missing install raises an `ImportError` naming the `sqlalchemy` extra.

- [ ] **Step 1: Write failing tests:**
  - Mongo:
    - exact dicts for each op/type pair;
    - **Review Focus 5:** for every `conformance/filters/*.json`, run `to_mongo(expected)` through mongomock over a fixed document set (strings, ints, floats, bools, nulls, missing fields), and assert the matched ids equal those where Python `evaluate`-equivalent leaf semantics match. Implement a small reference interpreter of the leaf contract in the test, independent of the translator.
  - SQLAlchemy, on SQLite in memory with `Invoice(id int pk, team_id str, amount int, paid bool, meta JSON)`:
    - `test_string_value_on_int_column_matches_nothing`
    - `test_bool_never_matches_number`
    - `test_null_never_matches_ne`
    - `test_json_column_is_false`
    - `test_unknown_field_false`
    - `test_all_none_modes`
    - one test per op against real rows
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the SDK suite** → 100%.
- [ ] **Step 5: Commit.** `git commit -m "feat(sdk): translate list filters to SQLAlchemy and Mongo with type guards"`

### Task S5: The guard middleware, route matching and decision logs

**Files:**
- Create: `sdks/python/src/osiki_sdk/{guard.py,routes.py,logs.py}`, `sdks/python/tests/{test_guard.py,test_routes.py,test_logs.py}`
- Modify: `sdks/python/src/osiki_sdk/{osiki.py,__init__.py}`, `sdks/python/README.md`

**Interfaces:**
- Usage (the "two lines"):
  ```python
  osiki = Osiki(base_url=OSIKI_URL, api_key=OSIKI_KEY, user_id=lambda req: decode_access_token(req.headers.get("authorization")))
  app.add_middleware(OsikiGuard, osiki=osiki)
  ```
- `routes.py`:
  - `RouteMatch = Matched | Opaque | NoMatch`, where:
    - `Matched(path: str, params: dict[str, str])` is the first `Match.FULL` on a `starlette.routing.Route` (FastAPI's `APIRoute` included);
    - `Opaque()` is a `Match.FULL` on anything else (a `Mount`, a `Host`, a sub-app);
    - `NoMatch()` covers no FULL match, including PARTIAL (Starlette's 405).
  - `match_route(app: Starlette, scope: Scope) -> RouteMatch`: a `HEAD` request matches as `GET`.
  - `list_routes(app: Starlette) -> list[tuple[str, str]]`: every `(METHOD, path)` of `Route`s, excluding HEAD and OPTIONS, sorted.
- `class DecisionLogBatcher(client: EngineClient, config: OsikiConfig)`:
  - `record(entry: dict[str, Any]) -> None` is non-blocking. Every denial is kept; a success is kept when `random.random() < log_success_sample_rate`.
  - A background flush runs every `log_flush_interval`, or as soon as `log_batch_size` entries are pending.
  - A send failure is logged and the batch dropped.
  - The queue is bounded at 10,000; on overflow the oldest entries are dropped.
  - `start()`, and `stop()` which flushes.
- `class OsikiGuard(app: ASGIApp, osiki: Osiki)` is pure ASGI. Non-HTTP scopes pass through. Per HTTP request, in order:
  1. `await osiki.start()`, then `await osiki.discover(scope["app"])`. Both are idempotent.
  2. `OPTIONS` passes through.
  3. `match_route`: `NoMatch` passes through. `Opaque` is treated as an unmapped route (step 6), not passed through. A `Matched` `(METHOD, template)` in `config.public_routes` passes through.
  4. Store unavailable: `GET`/`HEAD` use the mapping's `on_unavailable` if a snapshot mapping is known, else `config.read_on_unavailable`. Other methods use `on_unavailable` if known, else `"deny"`. A deny → 503 `{"detail":"authorization unavailable"}`.
  5. Look up the mapping by `(METHOD, template)`, with `HEAD` looked up as `GET`.
  6. No mapping (or `Opaque`): `settings.unmapped == "deny"` → 403 `{"detail":"forbidden","reason":"unmapped"}`; `"allow"` → pass, with one `logging.warning` per route.
  7. A `public` mapping passes.
  8. The user resolver (sync or async) returns `None` or raises → 401 `{"detail":"unauthenticated"}`.
  9. The tenant resolver, if any: `scope = {"tenant_id": t}` when `t`. A raise → 401.
  10. A mapping with `record_type`:
      - no loader → 503 `{"detail":"authorization misconfigured"}`, logged once;
      - the loader raises → 503;
      - the loader returns `None` → 404 `{"detail":"not found"}`;
      - otherwise `to_record` the result, and set `scope["state"]["osiki_record"]` to the raw object (`request.state.osiki_record`).
  11. A missing bundle → 403 `{"detail":"forbidden","reason":"unknown_user"}`. Otherwise call `decide`: a deny → 403 with `"reason": denial_reason`; an allow → call the app.
  12. `batcher.record({timestamp, user_id, resource, action, scope, allowed, matched_permission, condition, denial_reason, latency_ms})`.

  Any unexpected exception inside steps 1–12 → 503 `{"detail":"authorization unavailable"}`. It never falls through to the app.

- [ ] **Step 1: Write failing tests.** Use a FastAPI app with `GET /invoices`, `GET /invoices/{invoice_id}`, `DELETE /invoices/{invoice_id}`, `POST /invoices`, `GET /health`, `POST /auth/login`, and a `Mount("/static", ...)`. Use a fake client and `httpx.AsyncClient(transport=httpx.ASGITransport(app))`. The resolver decodes a toy bearer token from the `Authorization` header.
  - `test_template_match_with_path_param` (**Review Focus 3**)
  - `test_unmapped_denied_in_deny_env` / `test_unmapped_allowed_with_single_warning_in_allow_env`
  - `test_mount_is_treated_as_unmapped`
  - `test_public_routes_in_code_skip_snapshot`: the login route works in a deny environment with no mapping and no token.
  - `test_public_mapping_skips_user_resolution`
  - `test_resolver_decodes_bearer_header`
  - `test_missing_user_401` / `test_resolver_exception_401`
  - `test_record_rule_allows_own_team_denies_other`
  - `test_loader_none_404` / `test_loader_raises_503` / `test_missing_loader_503` (**Review Focus 4**)
  - `test_record_shared_on_request_state`: one loader call, and the handler sees the same object.
  - `test_converted_objectid_record_matches_rule`
  - `test_cold_start_write_503_read_default_503_read_allow_when_configured` (**Review Focus 1**)
  - `test_head_follows_get_mapping` / `test_options_passes_through`
  - `test_unknown_path_falls_through_to_404`
  - `test_concurrent_cold_requests_start_once`
  - `test_routes_reported_once`
  - `test_guard_internal_error_returns_503`
  - `test_unknown_user_403`
  - Logs:
    - `test_denials_always_logged`
    - `test_successes_sampled`
    - `test_flush_on_batch_size_and_interval`
    - `test_flush_failure_dropped`
    - `test_queue_bounded`
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Implement.** Then write the SDK README, which opens with "set up a dev environment": `PUT /settings {"unmapped":"allow"}`, plus `public_routes` for login and health. It then covers:
  - install (path/git until M4)
  - the two lines
  - the resolver as the trust boundary (decode the JWT yourself)
  - middleware ordering with auth middleware
  - tenant resolver
  - loaders and `request.state.osiki_record`
  - `check`/`filter`
  - the translators
  - sync
  - failure modes
  - every config field
- [ ] **Step 4: Run the SDK suite** → 100%, with mypy, ruff and black clean.
- [ ] **Step 5: Commit.** `git commit -m "feat(sdk): add OsikiGuard middleware with route matching and batched decision logs"`

### Task S6: End-to-end round trip against the real engine

**Files:**
- Create: `tests/e2e/test_sdk_roundtrip.py`
- Modify: root `pyproject.toml` (dev dependency `osiki-sdk = {path = "sdks/python", develop = true}`), `poetry.lock`, root `README.md` (SDK section and link)

**Interfaces:**
- Consumes:
  - the engine e2e app and fixtures (`tests/e2e/conftest.py`, mock repositories per environment);
  - the SDK's `Osiki`/`OsikiGuard`, with `transport=httpx.ASGITransport(engine_app)` and `base_url="http://engine"`.
- The developer's app is a separate FastAPI app wrapped in `OsikiGuard`.

- [ ] **Step 1: Write failing tests:**
  - `test_full_flow`:
    - Via the engine API: permission `invoices:read`, condition `own_team`, a role with the conditional grant, user `kofi` (`team_id=t1`), tenant `acme`, the membership, then the assignment.
    - `await osiki.discover(dev_app)`, then `GET /endpoints` lists `GET /invoices/{invoice_id}` as unmapped.
    - `PUT /endpoints/mapping` (`record_type="invoice"`, `record_id_param="invoice_id"`), then `await osiki._store.poll_once()`.
    - The t1 invoice → 200; the t2 invoice → 403 `condition_failed`.
  - `test_revocation_propagates_after_poll` (**Review Focus 2**): allowed, then revoke via the engine API (`?tenant_id=acme`), then `poll_once()`, then 403 `no_permission`.
  - `test_filter_roundtrip_sqlalchemy`: `to_sqlalchemy(await osiki.filter(...), Invoice)` over SQLite rows returns only t1.
  - `test_decision_logs_reach_engine`: after `await osiki.aclose()`, the engine's access logs include `source="sdk"` entries.
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Wire the dev dependency** (Poetry 2.3: `poetry lock && poetry install`; `lock` no longer upgrades unrelated packages by default). Keep root coverage measured on `osiki/` only, at 100%. Add the README sections.
- [ ] **Step 4: Run everything:** the root suite at 100%, `poetry run mypy .`, `make lint`, `python scripts/sync_sdk_decision.py --check`, and the SDK suite at 100%.
- [ ] **Step 5: Commit.** `git commit -m "test: end-to-end round trip of osiki-sdk against the engine"`

**M2a done:**
- The engine and SDK suites are both green, and the drift check passes.
- `sdk.yml` is green on 3.11 and 3.13 in the PR.
