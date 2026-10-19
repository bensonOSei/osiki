# M2a — Python SDK and Endpoint Map: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A FastAPI developer adds Osiki with about two lines, gets every route checked locally against the cached snapshot, and can map endpoints to permissions from the engine. This includes record-level rules, list filters for SQLAlchemy and Mongo, user and tenant sync, and failure modes that deny safely.

**Architecture:** Changes on the engine side:
- an endpoint map (discovered routes plus developer mappings) and per-environment settings, both shipped inside the snapshot;
- an `assignments_version` counter, so SDKs learn about role, membership and user changes within seconds by polling.

The SDK lives in this repo at `sdks/python` and is published as `osiki-sdk`, imported as `osiki_sdk`. It carries a byte-identical copy of `osiki/decision/`, which CI keeps in sync, and it decides locally. Its pure ASGI middleware does the following:
- matches each request to its route template;
- resolves the user and tenant;
- loads the record through a registered loader;
- calls `decide`;
- sends decision logs in background batches.

**Tech Stack:** Python 3.11+ (SDK), Python 3.13 (engine), httpx, pydantic 2, Starlette/FastAPI, SQLAlchemy 2 (optional extra), pytest + pytest-asyncio, Poetry.

**Spec:** `docs/superpowers/specs/2026-10-18-osiki-cloud-design.md` (§3 escape hatch, §5.2 guard, §5.3 unreachable, §5.4 record checks, §5.5 sync, §5.10 HTTP API, §6 performance). Prior work: `docs/superpowers/plans/2026-10-18-m1-engine-ready-for-cloud.md` and `conformance/README.md`.

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
- One PR for all of M2a.

## Review Focus

1. **Engine unreachable at cold start** (no snapshot has ever loaded): writes get 503, reads follow `read_on_unavailable` (default deny). The app never sees a 500 or an allow. Pinned in Task S5.
2. **Revocation while a bundle is cached:** after the next poll tick (`poll_interval`), the same request is denied. Pinned in Task S6 (end to end).
3. **Requests are matched by route template, not raw path:** `/invoices/42` matches `GET /invoices/{invoice_id}`. An unmapped route is denied in `unmapped="deny"` environments and allowed with a warning in `"allow"`. `HEAD` and `OPTIONS` follow their GET route or pass through, never a 500. Pinned in Task S5.
4. **A loader that returns `None`, raises, or returns non-JSON values** (datetime, ObjectId, UUID, Decimal): `None` gives 404, an exception gives 503 (fail closed), and values are converted with `to_record`. A rule over a converted id still matches. Pinned in Task S5.
5. **Filter translation keeps the leaf `type` guard:** a string value never matches a numeric column or field, and a boolean never matches a number, in both the SQLAlchemy and the Mongo translators. Pinned in Task S4.

---

## File Structure

```
osiki/decision/models.py, rules.py      MOD  TypeAlias instead of `type` statements
osiki/decision/models.py                MOD  Snapshot gains endpoints + settings
osiki/models/endpoint.py                NEW  DiscoveredEndpoint, EndpointMapping
osiki/models/environment_state.py       MOD  assignments_version, unmapped_policy
osiki/repositories/endpoints/           NEW  discovered + mapping repos
osiki/repositories/environment_state/   MOD  bump_assignments_version, settings
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
    __init__.py            public API: Osiki, OsikiGuard, to_record, Decision, FilterResult
    _decision/             vendored copy (generated)
    config.py              OsikiConfig
    client.py              EngineClient (HTTP)
    store.py               PolicyStore (snapshot, bundles, refresher)
    osiki.py               Osiki facade: check, filter, loader registry, sync, lifecycle
    records.py             to_record
    filters/sqlalchemy.py  to_sqlalchemy
    filters/mongo.py       to_mongo
    guard.py               OsikiGuard ASGI middleware
    routes.py              route matching + discovery
    logs.py                DecisionLogBatcher
  tests/                   unit tests + conformance runner
.github/workflows/sdk.yml               NEW  SDK CI (3.11, 3.13) + drift check
tests/e2e/test_sdk_roundtrip.py         NEW  SDK against the in-process engine
```

---

## Phase E — Engine

### Task E1: Endpoint map, environment settings and assignments version

**Files:**
- Create: `osiki/models/endpoint.py`, `osiki/repositories/endpoints/{__init__,base_endpoint_repository,mongodb_endpoint_repository}.py`, `osiki/schemas/endpoint.py`, `osiki/api/routes/endpoints.py`, `osiki/api/routes/settings.py`, `tests/e2e/test_endpoints.py`, `tests/e2e/test_settings.py`, `tests/integration/repositories/test_endpoint_repository.py`
- Modify:
  - `osiki/decision/models.py`, `osiki/decision/rules.py` (3.11 compatibility; Snapshot fields)
  - `osiki/models/environment_state.py`, `osiki/repositories/environment_state/*`
  - the Mongo repos for users, tenants, tenant_members, user_roles, group_roles, user_groups and groups (assignment bumps)
  - `osiki/services/snapshot_builder/snapshot_builder.py`, `osiki/api/routes/snapshot.py`, `osiki/api/dependencies.py`, `osiki/main.py`, `osiki/configs/database.py`
  - mocks, factories and conftests

**Interfaces:**
- Produces, in `osiki/decision/models.py` (pure, 3.11-compatible):
  - `EndpointEntry(_Frozen)`:
    - `method: str` (upper-case)
    - `path: str` (route template, e.g. `"/api/v1/invoices/{invoice_id}"`)
    - `permission: str | None` (`"res:act"`; `None` only when `public`)
    - `record_type: str | None`
    - `record_id_param: str | None`
    - `public: bool = False`
    - `on_unavailable: Literal["deny","allow"] | None = None` (`None` means the SDK default)
  - `EnvironmentSettings(_Frozen)`: `unmapped: Literal["deny","allow"] = "deny"`
  - `Snapshot` gains `endpoints: list[EndpointEntry] = []` and `settings: EnvironmentSettings = EnvironmentSettings()`. Both have defaults, so existing conformance fixtures stay valid.
  - `Via` and `DenialReason` become `TypeAlias` assignments; `FilterNode` in `rules.py` likewise.
- Produces, in the engine:
  - `DiscoveredEndpoint(Document, EnvironmentMixin)`: `method`, `path`, `first_seen: float`, `last_seen: float`; unique `(environment_id, method, path)`.
  - `EndpointMapping(Document, EnvironmentMixin, TimestampMixin)`: the `EndpointEntry` fields; unique `(environment_id, method, path)`.
  - `BaseEndpointRepository(environment_id, state)`:
    - `record_discovered(endpoints: list[tuple[str, str]], now: float) -> int` (upsert; sets `last_seen`)
    - `list_discovered() -> list[DiscoveredEndpoint]`
    - `upsert_mapping(entry: EndpointEntry) -> EndpointMapping` (bumps config)
    - `delete_mapping(method: str, path: str) -> bool` (bumps config on success)
    - `list_mappings() -> list[EndpointMapping]`
  - `EnvironmentState` gains `assignments_version: int = 0` and `unmapped_policy: Literal["deny","allow"] = "deny"`.
  - `BaseEnvironmentStateRepository` gains:
    - `get_assignments_version() -> int`
    - `bump_assignments_version() -> int` (atomic `$inc` upsert)
    - `get_settings() -> EnvironmentSettings`
    - `update_settings(settings: EnvironmentSettings) -> EnvironmentSettings` (bumps config)
- Routes:
  - `POST /endpoints/discovered` with body `{"endpoints": [{"method","path"}]}` (1–1000 items) → 202 `{"recorded": n}`.
  - `GET /endpoints` → `list[EndpointStatusRead{method, path, mapping: EndpointEntry | null, last_seen: float | null}]`. This is the union of discovered and mapped endpoints, sorted by `(path, method)`.
  - `PUT /endpoints/mapping` with body `EndpointEntry` → 200 `EndpointEntry`.
  - `DELETE /endpoints/mapping?method=&path=` → 204, or 404 if absent.
  - `GET /settings` and `PUT /settings` → `EnvironmentSettings`.
  - `GET /snapshot/version` → `{"version": int, "assignments_version": int}`.
- Validation (422):
  - `method` must be one of GET, POST, PUT, PATCH, DELETE;
  - `path` must start with `/`;
  - `permission` must match `^[^:]+:[^:]+$`;
  - `public=False` requires `permission`;
  - `record_type` and `record_id_param` must be set together, and `record_id_param` must appear as `{name}` in `path`;
  - `record_type` slug `^[a-z][a-z0-9_]{0,62}$`.
- The assignments version is bumped after every successful write in:
  - users: upsert, create, update, deactivate
  - tenants: upsert
  - tenant_members: add, remove
  - user_roles: create, revoke
  - group_roles: create, revoke
  - user_groups: create, remove
  - groups: deactivate, reactivate

- [ ] **Step 1: Write failing tests.**
  - `test_snapshot_includes_mappings_and_settings`: `PUT /endpoints/mapping` with `{"method":"DELETE","path":"/invoices/{id}","permission":"invoices:delete","record_type":"invoice","record_id_param":"id"}`, then `GET /snapshot` → `endpoints[0]` equals the body and `settings == {"unmapped":"deny"}`.
  - `test_mapping_write_bumps_config_version`, `test_settings_write_bumps_config_version`.
  - `test_discovered_then_listed_as_unmapped`.
  - `test_mapping_validation_422`, parametrized: missing permission when not public; `record_id_param` absent from the path; bad method; `"a:b:c"` permission.
  - `test_delete_mapping_404`.
  - `test_assignments_version_bumps_on_every_assignment_write`: parametrized over each write listed above, each strictly increases.
  - `test_snapshot_version_endpoint_returns_both`.
  - `test_endpoints_env_isolated`.
  - `test_decision_package_is_311_compatible`: parse every file in `osiki/decision/` with `ast.parse(source, feature_version=(3, 11))` and assert no `ast.TypeAlias` nodes.
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Implement.** The snapshot builder renders mappings sorted by `(path, method)` and settings from the state repo.
- [ ] **Step 4: Run the full suite and checks.** `poetry run pytest --cov=osiki` → 100%; `make lint`; `poetry run mypy .` clean.
- [ ] **Step 5: Commit.** `git commit -m "feat: add endpoint map, environment settings and assignments version"`

---

## Phase S — SDK

### Task S1: SDK package, vendored decision core, CI

**Files:**
- Create:
  - `scripts/sync_sdk_decision.py`
  - `sdks/python/{pyproject.toml,README.md}`
  - `sdks/python/src/osiki_sdk/__init__.py`
  - `sdks/python/src/osiki_sdk/_decision/` (generated)
  - `sdks/python/tests/test_conformance.py`
  - `.github/workflows/sdk.yml`
- Modify: `.github/workflows/ci.yml` (add the drift-check step), root `Makefile` (`sdk-sync`, `sdk-test`)

**Interfaces:**
- `scripts/sync_sdk_decision.py [--check]`:
  - copies every `osiki/decision/*.py` to `sdks/python/src/osiki_sdk/_decision/`;
  - removes stale files;
  - prepends nothing, so copies are byte-identical;
  - `--check` exits 1 and lists the differing files when the copy is stale.
- `sdks/python/pyproject.toml`:
  - Poetry, name `osiki-sdk`, version `0.1.0`, packages from `src`, python `>=3.11`;
  - deps `httpx>=0.27`, `pydantic>=2.6`, `starlette>=0.37`;
  - extra `sqlalchemy = ["sqlalchemy>=2"]`;
  - dev: pytest, pytest-asyncio, pytest-cov, mypy, ruff, black, `fastapi`, `sqlalchemy`, `mongomock-motor` (only if a test needs it);
  - coverage `omit = ["src/osiki_sdk/_decision/*"]` with `fail_under = 100`.
- `sdks/python/tests/test_conformance.py` parametrizes over `../../conformance/{decisions,filters}/*.json` (repo-relative path) and runs `osiki_sdk._decision.decide`/`list_filter`. It mirrors the engine runner's strictness: exact keys, full model equality.
- `.github/workflows/sdk.yml` runs on PRs touching `sdks/**`, `osiki/decision/**`, `conformance/**` or `scripts/sync_sdk_decision.py`. Its matrix is Python 3.11 and 3.13, and it runs:
  - `python scripts/sync_sdk_decision.py --check`
  - `cd sdks/python && poetry install && poetry run black --check . && poetry run ruff check . && poetry run mypy src && poetry run pytest --cov=osiki_sdk`

- [ ] **Step 1: Write failing tests** for the sync script, in the root `tests/unit/test_sync_sdk_decision.py`:
  - `test_check_passes_when_identical`
  - `test_check_fails_and_names_file_on_drift` (copy, mutate one file, `--check` → exit 1 with the file name in output)
  - `test_sync_removes_stale_files`

  Use `tmp_path`, with source and destination passed as arguments (`main(argv)` takes `--source` and `--dest` defaulting to the repo paths).
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Implement** the script, run it to generate `_decision/`, then create the package skeleton and the conformance runner.
- [ ] **Step 4: Verify.**
  - `poetry run pytest tests/unit/test_sync_sdk_decision.py` passes.
  - `python scripts/sync_sdk_decision.py --check` exits 0.
  - `cd sdks/python && poetry install && poetry run pytest` passes all conformance cases.
  - Run under 3.11 if available (`poetry env use 3.11`); if 3.11 is not installed locally, CI's matrix covers it and the report must say so.
- [ ] **Step 5: Commit.** `git commit -m "feat: scaffold osiki-sdk with vendored decision core and drift check"`

### Task S2: Engine HTTP client

**Files:**
- Create: `sdks/python/src/osiki_sdk/{config.py,client.py,records.py}`, `sdks/python/tests/{test_client.py,test_records.py}`

**Interfaces:**
- `@dataclass(frozen=True) class OsikiConfig` with fields:
  - `base_url: str`
  - `environment: str = "default"`
  - `api_key: str | None = None`
  - `poll_interval: float = 2.0`
  - `bundle_ttl: float = 60.0` (safety net)
  - `bundle_cache_size: int = 10_000`
  - `read_on_unavailable: Literal["deny","allow"] = "deny"`
  - `log_success_sample_rate: float = 0.1`
  - `log_flush_interval: float = 2.0`
  - `log_batch_size: int = 100`
  - `request_timeout: float = 2.0`
- `class EngineClient(config, transport: httpx.AsyncBaseTransport | None = None)`. Every method is async and sends `X-Osiki-Environment` and `Authorization: Bearer <api_key>` when set. Methods:
  - `get_snapshot(etag: str | None) -> tuple[Snapshot | None, str | None]` (`(None, etag)` on 304)
  - `get_versions() -> tuple[int, int]` (config, assignments)
  - `get_bundle(user_id) -> UserBundle | None` (404 → `None`)
  - `report_endpoints(endpoints: list[tuple[str, str]]) -> None` (chunks of 1000)
  - `send_access_logs(entries: list[dict[str, Any]]) -> None` (chunks of 500)
  - `upsert_user(user_id, name=None, email=None, attributes=None) -> None`
  - `upsert_tenant(tenant_id, name, attributes=None) -> None`
  - `add_member(tenant_id, user_id) -> None`
  - `remove_member(tenant_id, user_id) -> bool`
  - `aclose() -> None`
- Errors: network errors and 5xx raise `EngineUnavailable(Exception)`. 4xx (other than the 404/304 handled above) raise `EngineError(status, body)`. Path segments are URL-encoded.
- `records.to_record(obj: Any) -> dict[str, Any]` accepts a Mapping, a pydantic model (`model_dump()`), a dataclass, or a SQLAlchemy model (column attributes via `sqlalchemy.inspect`, only when sqlalchemy is importable). It converts values recursively:
  - `ObjectId`, `UUID` (anything with `__class__.__name__ in {"ObjectId"}` or a `uuid.UUID` instance) → `str`
  - `datetime`/`date` → ISO string
  - `Decimal` → `float`
  - `Enum` → `.value`
  - sets and tuples → list
  - anything else non-JSON → `str`

- [ ] **Step 1: Write failing tests** using `httpx.MockTransport`:
  - `test_snapshot_304_returns_none_with_etag`
  - `test_headers_sent`: environment, plus bearer only when `api_key` is set
  - `test_bundle_404_none`
  - `test_5xx_and_connect_error_raise_unavailable`
  - `test_report_endpoints_chunks_1000`
  - `test_access_logs_chunks_500`
  - `test_user_id_url_encoded`: `"a/b"` → `/users/by-external/a%2Fb`
  - `test_to_record_converts_objectid_uuid_datetime_decimal_enum` (ObjectId via `bson` if installed, otherwise a stub class named `ObjectId`)
  - `test_to_record_sqlalchemy_model`
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `cd sdks/python && poetry run pytest --cov=osiki_sdk` → PASS at 100%.
- [ ] **Step 5: Commit.** `git commit -m "feat(sdk): add engine client, config and record conversion"`

### Task S3: Policy store and the `Osiki` facade (local check and filter, sync, lifecycle)

**Files:**
- Create: `sdks/python/src/osiki_sdk/{store.py,osiki.py}`, `sdks/python/tests/{test_store.py,test_osiki.py}`
- Modify: `sdks/python/src/osiki_sdk/__init__.py`

**Interfaces:**
- `class PolicyStore(client: EngineClient, config: OsikiConfig, clock: Callable[[], float] = time.monotonic)`:
  - `snapshot: Snapshot | None`
  - `async refresh_snapshot() -> None` (ETag-aware)
  - `async get_bundle(user_id) -> UserBundle | None`: LRU of `bundle_cache_size`; an entry expires after `bundle_ttl`; a miss fetches.
  - `async poll_once() -> None`: reads both versions. A changed config version → `refresh_snapshot()`. A changed assignments version → clear the bundle cache.
  - `async start() -> None`: first refresh, then a background task calling `poll_once` every `poll_interval`. Errors are logged and swallowed, and the last good snapshot is kept.
  - `async stop() -> None`
  - `available: bool`: a snapshot has been loaded at least once.
- `class Osiki(config: OsikiConfig | None = None, *, base_url: str | None = None, environment="default", api_key=None, user_id: UserResolver, tenant: TenantResolver | None = None, transport=None, **config_overrides)`:
  - `UserResolver = Callable[[Request], str | None | Awaitable[str | None]]` (Starlette `Request`); `TenantResolver` likewise.
  - `loader(record_type: str) -> Callable[[LoaderFn], LoaderFn]` decorator, where `LoaderFn = Callable[[str], Awaitable[Any | None]]`. Duplicate registration raises `ValueError`.
  - `async check(user_id: str, resource: str, action: str, *, tenant: str | None = None, record: Any | None = None) -> Decision`: the escape hatch. It converts `record` with `to_record`, uses the cached snapshot and bundle, and passes `now=time.time()`. An unknown user gives `Decision(allowed=False, denial_reason="no_permission")`. If the engine is unavailable, it raises `OsikiUnavailable`.
  - `async filter(user_id, resource, action, *, tenant=None) -> FilterResult`
  - `users`: `upsert(id, *, name=None, email=None, attributes=None)`
  - `tenants`: `upsert(id, *, name, attributes=None)`, `add_member(tenant_id, user_id)`, `remove_member(tenant_id, user_id)`. These are thin wrappers that also clear that user's cached bundle.
  - `async start() -> None`, `async aclose() -> None`, `started: bool`.
- `osiki_sdk.__init__` exports `Osiki`, `OsikiConfig`, `Decision`, `FilterResult`, `to_record`, `OsikiUnavailable`, `EngineError`.

- [ ] **Step 1: Write failing tests.** Use a fake `EngineClient` (an in-memory class with the same methods) and a manual clock.
  - `test_check_allows_via_cached_snapshot_and_bundle`: with the client counting calls, a second check makes no network call.
  - `test_assignments_version_change_clears_bundles`
  - `test_config_version_change_refreshes_snapshot`
  - `test_bundle_ttl_expiry_refetches`
  - `test_lru_evicts_oldest`
  - `test_poll_error_keeps_last_snapshot`
  - `test_check_unavailable_before_first_snapshot_raises`
  - `test_check_converts_record_with_to_record` (datetime field compared as ISO string)
  - `test_filter_returns_typed_filter`
  - `test_sync_wrappers_call_client_and_invalidate_user`
  - `test_duplicate_loader_raises`
  - `test_check_latency_under_1ms`: 1,000 warm checks, median under 1 ms. Mark it `@pytest.mark.perf` and run it in CI; if CI noise makes it flaky, assert a 2 ms median and log the actual figure.
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the SDK suite** → PASS at 100%.
- [ ] **Step 5: Commit.** `git commit -m "feat(sdk): add policy store with version polling and local check/filter"`

### Task S4: List-filter translators

**Files:**
- Create: `sdks/python/src/osiki_sdk/filters/{__init__,sqlalchemy,mongo}.py`, `sdks/python/tests/{test_filter_sqlalchemy.py,test_filter_mongo.py}`

**Interfaces:**
- Leaf contract (from `conformance/README.md`): a leaf matches only when the field is present, non-null, of the leaf's `type` class (a boolean is never a number), and satisfies op and value. Ops: `eq ne lt lte gt gte in nin`.
- `to_mongo(result: FilterResult) -> dict[str, Any] | None`:
  - `mode="all"` → `{}`
  - `mode="none"` → `None` (the caller must return nothing)
  - `"filter"`: `and`/`or` become `$and`/`$or`. A leaf becomes `{field: {"$type": T, "$<op>": value}}`, where:
    - T is `"string"` for string, `["int","long","double"]` for number, `"bool"` for boolean;
    - `eq`/`ne`/`lt`/`lte`/`gt`/`gte`/`in`/`nin` map to `$eq`/`$ne`/`$lt`/`$lte`/`$gt`/`$gte`/`$in`/`$nin`.
- `to_sqlalchemy(result: FilterResult, model: type[Any]) -> ColumnElement[bool]`:
  - `"all"` → `true()`; `"none"` → `false()`.
  - A leaf on a column whose `type.python_type` doesn't match the leaf's class gives `false()`. The classes are `str`; `int`/`float`/`Decimal` for number; `bool` for boolean.
  - A leaf on a field the model doesn't have gives `false()`.
  - Otherwise the leaf is `and_(col.is_not(None), <op>)`, using `in_`/`not_in` for `in`/`nin`.
- `osiki_sdk.filters` exports both. The SQLAlchemy import is lazy, with a clear `ImportError` message naming the `sqlalchemy` extra.

- [ ] **Step 1: Write failing tests.**
  - Mongo: one test per op/type pair, comparing the exact dict.
  - Mongo: evaluate every `conformance/filters/*.json` expected filter through `mongomock` against a fixed set of documents, and assert the result equals Python `evaluate` over the same documents (**Review Focus 5**).
  - SQLAlchemy: an in-memory SQLite model `Invoice(id int, team_id str, amount int, paid bool)`.
    - `test_string_value_on_int_column_matches_nothing`
    - `test_bool_never_matches_number`
    - `test_null_never_matches_ne`
    - `test_all_none_modes`
    - `test_unknown_field_false`
    - one test per op against real rows
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the SDK suite** → PASS at 100%.
- [ ] **Step 5: Commit.** `git commit -m "feat(sdk): translate list filters to SQLAlchemy and Mongo with type guards"`

### Task S5: The guard middleware, route discovery and decision logs

**Files:**
- Create: `sdks/python/src/osiki_sdk/{guard.py,routes.py,logs.py}`, `sdks/python/tests/{test_guard.py,test_routes.py,test_logs.py}`
- Modify: `sdks/python/src/osiki_sdk/{osiki.py,__init__.py}`, `sdks/python/README.md`

**Interfaces:**
- Usage (the "two lines"):
  ```python
  osiki = Osiki(base_url=..., api_key=..., user_id=lambda req: req.state.user.id)
  app.add_middleware(OsikiGuard, osiki=osiki)
  ```
- `routes.match_route(app: Starlette, scope: Scope) -> tuple[str, dict[str, str]] | None`:
  - iterates `app.router.routes`;
  - returns `(route.path, path_params)` for the first `Match.FULL`;
  - `HEAD` matches as `GET`;
  - mounts and other non-`Route` entries return `None`.
- `routes.list_routes(app) -> list[tuple[str, str]]`: every `(method, path)` for `APIRoute`/`Route`, excluding HEAD and OPTIONS.
- `class DecisionLogBatcher(client, config)`:
  - `record(entry: dict) -> None` is non-blocking. Every denial is kept; a success is kept when `random.random() < log_success_sample_rate`.
  - A background flush runs every `log_flush_interval` or when `log_batch_size` entries are pending, via `client.send_access_logs`.
  - Failures are logged and dropped.
  - The queue is bounded at 10,000; on overflow the oldest entries are dropped.
  - `start()` and `stop()` flush.
- `class OsikiGuard(app: ASGIApp, osiki: Osiki)`, a pure ASGI middleware. On each HTTP request:
  1. On first use: `await osiki.start()` if not started; report `list_routes(scope["app"])` once via `client.report_endpoints`, in a background task whose failure is ignored; start the batcher.
  2. `OPTIONS` passes through.
  3. Match the route. If there is no match → pass through, so the app's own 404 handles it.
  4. If the store is unavailable: `GET`/`HEAD` follow the mapping's `on_unavailable`, else `config.read_on_unavailable`; any other method follows `on_unavailable`, else `"deny"`. A deny is 503 `{"detail":"authorization unavailable"}`.
  5. Find the mapping `(method, template)` in the snapshot. If there is none, apply `settings.unmapped`: `"deny"` → 403 `{"detail":"forbidden","reason":"unmapped"}`; `"allow"` → pass, plus a `logging.warning` once per route.
  6. `public` → pass.
  7. Resolve the user (sync or async resolver). `None` or an exception → 401 `{"detail":"unauthenticated"}`.
  8. Resolve the tenant (optional) and build `scope = {"tenant_id": t}` when present.
  9. If the mapping has a `record_type`:
     - no registered loader → 503 `{"detail":"authorization misconfigured"}`, logged once;
     - the loader raises → 503;
     - the loader returns `None` → 404 `{"detail":"not found"}`;
     - otherwise `to_record`, and store the raw object on `scope["state"]["osiki_record"]` (`request.state.osiki_record`).
  10. Call `decide`. A deny → 403 `{"detail":"forbidden","reason": denial_reason}`; an allow → call the app.
  11. Record a log entry with `{timestamp, user_id, resource, action, scope, allowed, matched_permission, condition, denial_reason, latency_ms}`.

  Any unexpected exception inside the guard → 503. It never falls through to the app.

- [ ] **Step 1: Write failing tests.** Build a FastAPI app with the routes `GET /invoices`, `GET /invoices/{invoice_id}`, `DELETE /invoices/{invoice_id}`, `POST /invoices`, `GET /health`, using a fake client that serves a snapshot and bundles. Use `httpx.ASGITransport` with `AsyncClient`.
  - `test_template_match_with_path_param` (**Review Focus 3**)
  - `test_unmapped_denied_in_deny_env` / `test_unmapped_allowed_with_single_warning_in_allow_env` (caplog)
  - `test_public_route_skips_user_resolution`
  - `test_missing_user_401` / `test_resolver_exception_401`
  - `test_record_rule_allows_own_team_denies_other`
  - `test_loader_none_404` / `test_loader_raises_503` / `test_missing_loader_503` (**Review Focus 4**)
  - `test_record_shared_on_request_state`: the handler sees the same object, and the loader is called once
  - `test_converted_objectid_record_matches_rule`
  - `test_cold_start_unavailable_write_503_read_default_503_read_allow_when_configured` (**Review Focus 1**)
  - `test_head_follows_get_mapping` / `test_options_passes_through`
  - `test_unknown_path_falls_through_to_404`
  - `test_routes_reported_once`
  - `test_guard_internal_error_returns_503`
  - Logs: `test_denials_always_logged`, `test_successes_sampled`, `test_flush_on_batch_size_and_interval`, `test_flush_failure_dropped`, `test_queue_bounded`
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Implement.** Write the SDK README covering:
  - install (path/git until M4)
  - the two lines
  - user and tenant resolvers
  - loaders and `request.state.osiki_record`
  - the `check` and `filter` escape hatches
  - the SQLAlchemy and Mongo translators
  - sync
  - failure modes
  - configuration
- [ ] **Step 4: Run the SDK suite** → PASS at 100%, with mypy, ruff and black clean.
- [ ] **Step 5: Commit.** `git commit -m "feat(sdk): add OsikiGuard middleware with route discovery and batched decision logs"`

### Task S6: End-to-end round trip against the real engine

**Files:**
- Create: `tests/e2e/test_sdk_roundtrip.py`
- Modify: root `pyproject.toml` (dev dependency `osiki-sdk = {path = "sdks/python", develop = true}`), `poetry.lock`, root `README.md` (SDK section and link)

**Interfaces:**
- Consumes: the engine e2e fixtures (`tests/e2e/conftest.py` app with mock repos) and the SDK `Osiki`/`OsikiGuard`/`EngineClient`, with `transport=httpx.ASGITransport(engine_app)`.
- The developer's app is a separate FastAPI app, guarded by `OsikiGuard`, whose `Osiki` talks to the in-process engine through that transport.

- [ ] **Step 1: Write failing tests:**
  - `test_full_flow`:
    - Via the engine API, create the permission `invoices:read`, the condition `own_team`, a role with the conditional grant, the user `kofi` with `team_id=t1`, the tenant `acme`, the membership and the assignment.
    - Start the guarded app, whose first request reports its routes. `GET /endpoints` lists `GET /invoices/{invoice_id}` as unmapped.
    - Map it via `PUT /endpoints/mapping` (`record_type="invoice"`, `record_id_param="invoice_id"`).
    - After `await osiki._store.poll_once()`, the team-t1 invoice → 200 and the team-t2 invoice → 403 `condition_failed`.
  - `test_revocation_propagates_after_poll` (**Review Focus 2**): allowed, then revoke via the engine API, then `poll_once()`, then 403 `no_permission`.
  - `test_filter_roundtrip_mongo_and_sqlalchemy`: `osiki.filter(...)` → `to_sqlalchemy` over SQLite rows returns only team t1.
  - `test_decision_logs_reach_engine`: after `await osiki.aclose()` (which flushes), the engine's access-log repo holds `source="sdk"` entries.
- [ ] **Step 2: Run them.** → FAIL.
- [ ] **Step 3: Wire the dev dependency** (`poetry lock --no-update && poetry install`). Make the root `pytest --cov=osiki` still measure only `osiki/` at 100%, and add the README sections.
- [ ] **Step 4: Run everything:** the root suite at 100%, `poetry run mypy .`, `make lint`, `python scripts/sync_sdk_decision.py --check`, and the SDK suite.
- [ ] **Step 5: Commit.** `git commit -m "test: end-to-end round trip of osiki-sdk against the engine"`

**M2a done:**
- The engine and SDK suites are both green, and the drift check passes.
- The `sdk.yml` workflow is green on 3.11 and 3.13 in the PR.
