# Osiki Cloud — Product Design

**Date:** 2026-10-18
**Status:** Draft for approval
**Owner:** Benson Osei-Mensah

Decisions marked **(builder's call)** were proposed during design and not explicitly chosen by the owner; they can be revisited during planning. Everything else was decided by the owner.

---

## 1. Intent

### The problem

Every project with a business dashboard and multiple staff users ends up rebuilding the same permissions layer: roles, permissions, checks on every endpoint, frontend show/hide logic, and admin screens for managing it. It is usually deferred ("build the product, attach permissions later"), and when it finally arrives it is either rushed or a full rewrite.

Evidence from the owner's own projects:

- **Poully** (FastAPI + Postgres): Osiki was copied in as an embedded library and rewritten from MongoDB to Postgres. It works, but it was a full rebuild, has no record-level checks, no permission caching (several DB queries per request), writes an access-log row to the DB on every check, and `GET /sync` returns all changed data to any logged-in user.
- **Elite Frames** (FastAPI + MongoDB): RBAC was deferred. A single `is_admin` boolean means any admin can see revenue and issue refunds. `PRODUCT.md` already asks for owner / sales / fulfillment roles that don't exist. New admins can only be created via a CLI script.

A second problem shows up once an app has business customers: those customers keep asking to change who can do what ("a role that can see reports but not export", "managers only see their own team's records", "the person who creates a payment can't approve it"). With hard-coded checks, every request becomes the developer's engineering work.

### The product

**Osiki Cloud** is a hosted permissions service for solo developers and startups. It:

1. Lets a developer add roles, permissions and **record-level** checks to an app — new or already built — with minimal code.
2. Lets the developer's **own customers** create and manage their own roles inside the developer's app, without the developer writing code. This is the most important capability.

The open-source Osiki engine (this repo) remains open source. The cloud platform around it is proprietary.

### Why someone uses it, and why they stay

- **Why they try it:** "Never write RBAC again." The next project gets roles, record-level rules and permission-aware UI in an afternoon.
- **Why they pay and stay:** their customers manage their own roles inside the app. Leaving Osiki would mean rebuilding that experience.

---

## 2. Goals, non-goals, anti-goals

### Goals

- Fastest setup of any permissions product: first protected endpoint in under 15 minutes from signup.
- Adding permissions to an **already built** app is a first-class path (endpoint discovery and mapping), not an afterthought.
- Record-level checks from day one.
- End-customer self-service roles (embedded and hosted).
- Never slows down the client's app (see §6).
- Easy to start, no ceiling (see §3).

### Non-goals

- **Authentication / identity.** Osiki does not handle login, passwords, sessions, signup, or invite emails. It works alongside whatever auth the app already has (home-grown JWT, Clerk, Supabase, Auth0…). Staying in the permissions niche is a deliberate decision.
- Storing the developer's business data. Record facts stay in the developer's database (§5.4).
- Offline / on-device apps (e.g. Mfaso) in the cloud product. The open-source engine may be embedded in such apps later; that's outside this spec.

### Anti-goals (failure even if it technically works)

- **Developers don't find it useful enough to adopt.** If it can't replace Poully's hand-built RBAC and give Elite Frames real staff roles, it has failed its first test.
- **Oversimplified to the point it can't be customized.** Simplicity must never come from removing power.
- **Latency.** If it measurably slows the client's app, it has failed.
- **Wrongly allowing access.** One incident of Osiki granting access it shouldn't would destroy trust. Tenant isolation and fail-safe defaults are non-negotiable.

---

## 3. Design principle: easy to start, no ceiling

Every layer has simple defaults and a deeper level for when a developer outgrows them:

| Layer | What it gives |
|---|---|
| Templates | Pick a starter (e.g. "Shop staff", "B2B SaaS team") and get sensible roles immediately. |
| Dashboard | Edit roles, permissions, endpoint mappings and rules by clicking. |
| Rules | Record-level conditions with full and/or logic over any record field and user/tenant attribute. |
| Code | Entire configuration as a roles file in the developer's repo, version-controlled, pushed via CLI. |
| Escape hatch | Direct `osiki.check()` calls anywhere automatic gates don't fit; plain HTTP API for any language. |

The test for every feature: does it make the simple case simpler **without** removing power from the complex case?

---

## 4. Account and tenancy model

```
Organization            the startup's Osiki account (billing unit)
├── Members             the startup's team: Owner / Admin / Developer / Viewer
└── Projects            one per app the startup builds
    └── Environments    dev, prod (staging on higher tiers); own API keys each
        ├── Configuration   permissions, roles, rules, endpoint map, constraints
        └── Tenants         the startup's customers (e.g. "Acme Corp")
            ├── Tenant admins + tenant-defined custom roles
            └── End users   people inside the tenant, known by ID only
```

- **Organization members** are themselves authorized by the Osiki engine (dogfooding).
- **Environments** are fully isolated from each other. Configuration is promoted dev → (staging) → prod, like code. A dashboard edit in one environment never affects another.
- **Tenants** are strictly isolated. A role, assignment, or rule in one tenant can never apply in another. **This is a change from the current engine**, whose scope matcher is permissive (an assignment with no scope matches any request; a request with no scope matches every assignment). In the cloud, a tenant-scoped request must only match assignments in that tenant or explicitly project-wide (developer-defined) assignments.
- **End users** are not authenticated by Osiki. The app tells Osiki about them (§5.5). Osiki stores user ID, display name, optional email, and tenant memberships — never credentials.
- A single-business app (like Elite Frames) is simply a project with one tenant.

### Two kinds of roles

- **Project roles:** defined by the developer (in the dashboard or roles file), available in every tenant. E.g. Owner, Sales, Fulfillment.
- **Tenant roles:** created by a tenant admin through the role manager (§5.7), visible only inside that tenant. Built only from permissions the developer has marked as customer-assignable.

### Tenant admins

**(Builder's call:)** Being a tenant admin is a permission Osiki stores and checks (a built-in permission such as `osiki.roles:manage`, granted through any role), not something the developer's token merely asserts. The developer's backend only identifies *who* the user is and *which tenant* they're acting in; Osiki decides whether they may manage roles. Tenant admins can never create or edit project roles; they may assign project roles to their users only where the developer has marked that project role customer-assignable.

### Scopes below the tenant

**(Builder's call:)** The engine's other scope dimensions (`region`, `branch_id`, `department`, and custom keys) stay, nested inside a tenant and matched strictly like tenants. UI for them is backlog (M5+). Most "only your own X" needs are expected to be met by record rules instead.

---

## 5. How it works

### 5.1 Integration in one picture

```
Developer's app                                     Osiki Cloud
┌──────────────────────────────────────────┐        ┌──────────────────────────┐
│  request → Osiki guard (SDK middleware)  │        │  Control plane           │
│    1. read user id from app's token      │◄──sync─┤  - config per env        │
│    2. match route → permission           │        │  - users / tenants       │
│    3. load record via loader (if rule)   │        │  - audit + access logs   │
│    4. evaluate locally (cached config)   │──logs─►│  - dashboard, billing    │
│    5. allow → handler / deny → 403       │ (async)│  - role manager (embed)  │
└──────────────────────────────────────────┘        └──────────────────────────┘
```

### 5.2 The guard (the "two lines")

A developer installs the SDK and adds the guard as middleware, e.g. for FastAPI:

```python
osiki = Osiki(api_key=..., user_id=lambda req: req.state.user.id)
app.add_middleware(osiki.guard())
```

- **Identifying the caller:** the developer tells the SDK once how to get the user ID (a token claim path or a small function). Tenant membership comes from Osiki's own records (§5.5), not the token — neither Poully's nor Elite Frames' tokens carry a tenant claim. When a user belongs to more than one tenant, the active tenant is supplied per request (header, path segment, or a function — configured once).
- **Endpoint discovery:** the SDK reports the app's routes (from the framework's router and/or OpenAPI spec) to Osiki, so the dashboard lists every endpoint ready to map. New routes show up as "unmapped".
- **Endpoint mapping:** in the dashboard, each route (method + path) maps to a permission and, for record endpoints, a record type and the path parameter holding its ID. E.g. `DELETE /invoices/{id}` → `invoices:delete` on record type `invoice` from `{id}`. Rules themselves live on role grants (§5.4), not on the endpoint.
- **Unmapped routes:** default behaviour is configurable per environment. **(Builder's call:)** default to *deny* in prod and *allow + warn* in dev, so retrofitting an existing app doesn't lock it out mid-migration.
- **Public routes** (login, health, webhooks) are marked public in the dashboard or in code.

### 5.3 When Osiki is unreachable

The SDK keeps working from its cached configuration. If a check genuinely can't be decided (e.g. cold start with no cache), each route follows its configured failure mode: **fail closed** (deny) or **fail open** (allow). **Writes fail closed by default; reads are configurable.** (Builder's call on defaults.)

### 5.4 Record-level checks (decided: data stays in the developer's app)

Osiki never receives the developer's business records.

- The developer registers **one loader per record type**, once:
  ```python
  @osiki.loader("invoice")
  async def load_invoice(id): return await db.invoices.get(id)
  ```
- **Rules attach to a role's grant of a permission** (builder's call): a role grants `invoices:read` either unconditionally or with a condition. So "Owners see all invoices; Managers only their team's" is two grants on two roles. If **any** of a user's grants allows the action, it's allowed (OR across grants).
- **Rules** are written in the dashboard or roles file as conditions over the record, the user, and the tenant, e.g. `record.team_id == user.team_id`, `record.created_by == user.id`, `record.amount < 10000`. Full and/or/not logic.
- **Named conditions:** the developer defines reusable, named conditions (e.g. "Own records only" = `record.created_by == user.id`, "Own team only"). These are what tenant admins choose from in the role manager (§5.7); tenant admins never write raw rule expressions.
- **Rule language v1 scope** (builder's call): conditions may reference only the record's own fields, user attributes, and tenant attributes — no joins, computed fields, or related tables. This guarantees every rule can be translated into a list filter. Broader expressiveness is a later extension, never at the cost of filterability being unknown at save time.
- User attributes used in rules (e.g. `team_id`) come from what the app sends on user sync (§5.5).
- **No double loading:** if the handler loads the record anyway, the loaded record can be shared with the guard via request context so the database is hit once.
- **List endpoints:** Osiki translates the applicable rule into a query filter the app applies to its own query (e.g. "only invoices where team_id = X"), so lists only return allowed records. Filter output targets the ORMs/drivers used by supported SDK stacks (initially SQLAlchemy and Beanie/Motor).
- **Rule language** must be safe to evaluate (no arbitrary code), deterministic, and identical across SDKs. Its exact syntax is left to the builder; it must support comparisons, membership, and/or/not, and references to `record`, `user`, `tenant`.

### 5.5 User and tenant sync

Osiki doesn't do auth, so the app tells it who exists:

- `osiki.users.upsert(id, name, email?, attributes?)` when a user is created or changed.
- `osiki.tenants.upsert(id, name)` and `osiki.tenants.add_member(tenant_id, user_id)` when a user joins a business.
- This keeps the role manager able to show real staff names ("Kofi") and keeps invites and login inside the app.

### 5.6 Frontend SDK (React)

Lifted from what Poully already has, so it's never rebuilt again:

- `<Can permission="invoices:delete">` to show/hide elements.
- Route guard component.
- `usePermissions()` hook.
- Backed by a "my permissions" endpoint scoped to the current user and tenant.

The frontend SDK is a UI convenience only; enforcement always happens server-side.

### 5.7 End-customer role manager (core feature)

One admin UI, delivered two ways:

- **Embedded** in the developer's app (`<OsikiRoleManager />` React component, plus an iframe option for other frontends). The developer's backend mints a short-lived token stating "this is tenant X's admin"; the component shows only that tenant's roles and users.
- **Hosted portal** at a branded URL (Osiki subdomain or the developer's own subdomain) for developers who don't want to touch frontend code.

Tenant admins (§4) can: create/edit/delete tenant roles, choose for each permission in a tenant role either "always" or one of the developer's named conditions (§5.4), assign/revoke tenant roles and customer-assignable project roles for their users, view their tenant's audit log.

Guardrails (all required):

- The developer marks which permissions (and project roles) are **customer-assignable**. Internal ones (e.g. `billing:refund` for the platform) are never visible to tenant admins.
- **No escalation:** a tenant admin can't grant anyone more than they themselves hold, compared per permission: a conditional grant is narrower than an unconditional one, so an admin who holds `invoices:read` only under "Own team only" cannot grant it unconditionally.
- **Constraints still apply** (e.g. "initiator can't approve"); the role manager rejects violating roles or assignments.
- Every change is written to an audit log visible to both the tenant and the developer.

### 5.8 Developer dashboard

Organization and members; projects and environments; API keys; endpoint list and mapping; permissions (with customer-assignable flag); project roles; rules; loaders/record types seen; users and tenants (read + search); audit and access logs; templates; billing.

### 5.9 Roles as code (CLI)

- `osiki init` writes a roles file (permissions, roles, rules, endpoint mappings) into the repo, optionally from a template.
- `osiki push --env dev` syncs it; `osiki pull` exports the dashboard state back to the file.
- The existing CLI (`cli/`, with generators and templates) is the starting point.
- **(Builder's call:)** when both the file and the dashboard are used, the file is the source of truth for project-level config in environments where it's been pushed; the dashboard shows those items as "managed by code". Tenant roles are never in the file.

### 5.10 HTTP API

Everything the SDKs do is available over a plain, documented HTTP API with an OpenAPI spec, so any language can integrate on day one (more code than two lines, but fully capable). This includes a network `check` endpoint for non-SDK callers.

---

## 6. Performance (hard requirement)

- **Local evaluation:** SDKs hold a snapshot of the environment's configuration (permissions, roles, rules, mappings, constraints) and evaluate in-process. Target: **< 1 ms** per check, excluding the developer's own loader query.
- **Per-user assignment cache:** fetched on a user's first request, cached; Osiki pushes invalidations on change so revocations take effect **within seconds**. **(Builder's call:)** a bounded TTL as a safety net in case a push is missed.
- **Config updates** are pushed to SDKs (streaming or long-poll — builder's choice) and applied within seconds.
- **Logging off the request path:** access/decision logs are batched and sent asynchronously. Poully's per-check DB write is the anti-pattern.
- **Network checks** (HTTP API, future gateway): **< 20 ms p95** from a nearby region.
- **SDK parity:** because each SDK evaluates locally, a shared conformance test suite (input config + request → expected decision) must pass for every SDK. Logic is identical everywhere. **(Builder's call:)** a conformance suite rather than a shared WASM core.

---

## 7. Existing engine: kept, prioritized

Nothing already built is thrown away. Existing engine capabilities all move into the product and are placed in releases:

| Capability (exists today) | Where it lands |
|---|---|
| `resource:action` permissions with wildcards | M1 |
| Roles with inheritance | M1 |
| Direct role assignments | M1 |
| Scopes (tenant isolation, made strict) | M1 |
| Audit logs | M1 (tenant-visible view in M3) |
| Access logs (denials + sampled successes) | M1, made async/batched |
| Redis caching | M1, extended into SDK snapshot + invalidation |
| Groups | Engine + API in M1; dashboard/role-manager UI in M5 |
| Constraints (mutual exclusion, cardinality, prerequisites) | Enforced from M1 (engine + role manager guardrail); dashboard UI in M5 |
| CLI with generators/templates | Basis for roles-as-code in M4 |

Engine changes required for the cloud (M1), split by licence (see §9):

- **Open-source engine:** a generic environment (namespace) concept; strict tenant isolation; record-level rule evaluation; snapshot export; change events. Self-hosters need these too.
- **Proprietary control plane, wrapping the engine:** organizations, members, projects, API-key management, billing, dashboard.

Specifically: every engine record scoped to an environment (e.g. `User.external_id` is globally unique today and must become unique per environment); strict tenant matching; record-level rule evaluation; configuration snapshot export; change events for SDK invalidation.

---

## 8. Releases

Built alongside other projects, no fixed date. Each release is useful on its own.

**M1 — Engine ready for the cloud (open-source engine only).** Environment namespacing, tenants and strict tenancy, grants with conditions (rule language and evaluation), snapshot export with a config version, constraint enforcement on assignment, async/batched access logging. Existing features carried over. Organizations, projects, API-key management and billing belong to the proprietary control plane and are built with M2/M4.

**M2 — Customer zero.** Python SDK (FastAPI first — both Poully and Elite Frames are FastAPI): guard, endpoint discovery, loaders, local evaluation, list filters, user/tenant sync. React SDK (`<Can>`, route guard, hook). Basic dashboard: roles, permissions, endpoint mapping, rules, users/tenants, logs. Poully's offline sync (`GET /sync`) uses the SDK's per-record-type list filter directly (the escape hatch), and the React SDK keeps the last known permissions for offline UI display only — enforcement stays server-side (builder's call). **Done when:** Poully runs on Osiki Cloud with its embedded RBAC code deleted, and Elite Frames has owner / sales / fulfillment roles with record-level rules.

**M3 — Your customers' customers.** Embedded role manager + hosted portal; customer-assignable permissions; no-escalation; constraint enforcement in the UI; tenant audit log.

**M4 — Public launch (Africa).** Self-serve signup, organizations and members, Paystack billing and plans, TypeScript SDK (Express, Next.js, Hono), CLI roles-as-code, templates, docs.

**M5+ — Backlog.** Groups and constraints UI; staging environment with promotion; zero-code gateway (proxy container enforcing the endpoint map; record checks via an app callback endpoint); Stripe + USD pricing for global launch; more SDKs (Go, PHP/Laravel, Ruby — ordered by demand); NestJS/Django adapters if not already done.

---

## 9. Business model

### Licensing

- **Open source (Apache 2.0):** the engine (including environments as a generic namespace, strict tenant isolation, rules, snapshots, change events) and the SDKs.
- **Proprietary:** the cloud platform — dashboard, endpoint mapping UI, role manager (embed + portal), organizations and members, projects, API-key management, billing, hosting.
- Note: Apache 2.0 allows anyone to host the engine commercially. Not a concern at this stage; future engine releases can move to a source-available licence if it becomes one.

### Pricing: subscription, charged by tenants

Charging per tenant (the developer's customers) rather than per check or per end user: per-check metering conflicts with local evaluation, per-user pricing scares solo devs, and tenant count grows with the developer's revenue.

Draft tiers (prices are placeholders):

| | Free | Starter (~$29/mo) | Growth (~$99/mo) | Business |
|---|---|---|---|---|
| Projects | 1 | 3 | 10 | Custom |
| Tenants | 3 | 25 | 250 | Custom |
| Environments | Dev + Prod | Dev + Prod | + Staging | Custom |
| Record-level rules | ✓ | ✓ | ✓ | ✓ |
| Embedded role manager | ✓ (Osiki badge) | ✓ (no badge) | ✓ + custom branding | ✓ |
| Constraints | | ✓ | ✓ | ✓ |
| Audit log history | 7 days | 30 days | 1 year | Custom |
| Team members | 1 | 3 | 10 | Unlimited |

- The free tier can run a real single-business app (one tenant) indefinitely.
- The role manager is on free (it's the stickiest feature); the badge drives upgrades.

### Over-limit and lapsed accounts

Permission checks **never** stop working because of billing — that would break the customer's live app and violate the fail-safe promise.

- **Over a plan limit** (e.g. a 4th tenant on Free): a grace period, after which creating new tenants/projects is blocked; existing ones keep working.
- **Lapsed payment** (including expired prepaid mobile-money plans): checks continue; the dashboard becomes read-only for a set number of days, then configuration changes stay blocked until payment resumes. Exact durations left to the builder.

### Market: Africa first, then global

- **Payments:** Paystack first (Ghana, Nigeria, Kenya, South Africa; cards + mobile money). Stripe at global launch.
- Mobile money recurring billing is unreliable → offer **prepaid monthly/annual** alongside card subscriptions.
- **Local-currency pricing** (GH₵, ₦…) adjusted for purchasing power, below the USD equivalents. USD at global launch.
- **Hosting:** start on the owner's existing VPS setup (deployed via CI/CD per the existing VPS app pattern). Region matters little for app latency since checks are local; revisit when global.
- **Data protection:** Ghana's Data Protection Act and Nigeria's NDPA apply, but Osiki stores only user IDs, display names, optional emails and role assignments — no credentials, no business records. Publish this as a selling point.

---

## 10. Success measures

**Customer zero (months 1–2)**
- Poully runs on Osiki Cloud with its embedded RBAC code deleted.
- Elite Frames has owner / sales / fulfillment roles with record-level rules, set up in under a day.
- No noticeable slowdown in either app.

**Outside developers (months 2–6)**
- First protected endpoint in under 15 minutes from signup.
- ~20 outside projects checking permissions in production.
- At least a few of them have their own customers creating roles via the role manager.
- Most projects still active after 30 days.

**Business (month 6)**
- First 3–5 paying customers.

**Always**
- Check latency within target (< 1 ms local, < 20 ms p95 network).
- Zero incidents of wrongly granted access.

---

## 11. Left to the builder

- Rule-language syntax and parser (within the constraints in §5.4).
- Config push mechanism (SSE, WebSocket, long-poll).
- Snapshot format and versioning.
- Control-plane stack beyond the existing engine (FastAPI + MongoDB + Redis today); dashboard frontend stack.
- Exact SDK API naming.
- Iframe/embed security details (token format, origin checks), within the "short-lived tenant-admin token minted by the developer's backend" model.
- Exact tier limits and local-currency prices.
