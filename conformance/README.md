# Osiki decision conformance fixtures

These JSON files pin the behaviour of Osiki's authorization decision. The
reference implementation is `osiki/decision/` (`decide.py`, `rules.py`,
`scope.py`). Every SDK that decides locally must load every file here and
produce exactly the `expected` value. `tests/conformance/test_conformance.py`
runs them against the reference implementation.

All files are plain JSON: strings, numbers, booleans, `null`, arrays and
objects. Times (`now`, `expires_at`) are numbers (Unix seconds). A number
written with a fraction (`1.0`) is the same number as one without (`1`).

## Layout

```
conformance/
  decisions/<name>.json   one decide() case per file
  filters/<name>.json     one list_filter() case per file
```

Each file's `name` equals its file name without `.json`. Cases whose name
starts with `rule_` exercise the record-rule evaluator through `decide`: the
user holds `docs:read` with condition `"rule"`, and the request reads
`docs:read`.

### Decision case

```json
{
  "name": "...",
  "snapshot": Snapshot,
  "bundle": UserBundle,
  "request": DecisionRequest,
  "expected": Decision
}
```

### Filter case

```json
{
  "name": "...",
  "snapshot": Snapshot,
  "bundle": UserBundle,
  "resource": "invoices",
  "action": "read",
  "scope": {"tenant_id": "acme"},
  "now": 1000,
  "expected": FilterResult
}
```

### Shapes

```
Snapshot        {environment_id: string, version: int,
                 roles: [RoleEntry], conditions: {key: Rule},
                 constraints: [ConstraintEntry],
                 endpoints: [EndpointEntry], settings: EnvironmentSettings}
EndpointEntry   {method, path, permission: "res:act"|null, record_type,
                 record_id_param, public: bool,
                 on_unavailable: "deny"|"allow"|null}   (not used by decide)
EnvironmentSettings {unmapped: "deny"|"allow"}          (not used by decide)
RoleEntry       {id, name, parent_id: string|null, grants: [GrantEntry]}
GrantEntry      {permission: "resource:action", condition: key|null}
ConstraintEntry {id, name, type, config: object}      (not used by decide)
UserBundle      {user_id: external id, attributes: object,
                 tenants: {tenant external id: attributes object},
                 assignments: [AssignmentEntry],
                 roles: [RoleEntry]}   (roles optional, default [])
AssignmentEntry {role_id, scope: {string: string},
                 expires_at: number|null, via: "direct"|"group"}
DecisionRequest {resource, action, scope: {string: string},
                 record: object|null, now: number}
Decision        {allowed: bool, matched_permission: string|null,
                 matched_via: "direct"|"group"|null, condition: key|null,
                 denial_reason: "no_permission"|"not_tenant_member"|
                                "condition_failed"|"record_required"|
                                "unknown_user"|null}
FilterResult    {mode: "all"|"none"|"filter", filter: FilterNode|null}
```

`decide` never returns `unknown_user`: callers return it when the user's bundle
is `null`, matching the server's `/authorization/check`.

`bundle.roles` is optional and defaults to `[]`. An SDK that ignores it sees
tenant-owned roles as missing and so grants less, never more.

A denial always has `matched_permission`, `matched_via` and `condition` set to
`null`. An unconditional allow has `condition: null`. Readers must ignore
unknown fields so that a newer snapshot still loads.

## `decide(snapshot, bundle, request)`

1. **Tenant membership.** If `request.scope` has a `tenant_id` that is not a
   key of `bundle.tenants`, deny `not_tenant_member`.
2. **Applying assignments.** Keep assignments whose `expires_at` is `null` or
   strictly greater than `now` (an assignment expiring exactly at `now` is
   expired), and whose scope matches: every key of the assignment's scope is
   present in the request scope with an equal value. An empty assignment scope
   matches every request, and a tenant-scoped assignment never applies to a
   request without that tenant.
3. **Role walk.** For each kept assignment, in list order, take the assigned
   role's grants, then its parent's (`parent_id`), and so on. A role is looked
   up in `snapshot.roles` and in `bundle.roles` (the user's tenant-owned
   roles); on an id clash the snapshot's role wins, so a bundle can never
   override a project role. Stop silently when a role id is missing from both
   or repeats (a cycle). Never
   raise: a corrupted hierarchy can only grant less. Each grant carries the
   assignment's `via`.
4. **Matching.** A grant matches when its `permission` is one of, from most
   to least specific: `resource:action`, `resource:*`, `*:action`, `*:*`.
   Order matching grants by specificity, then `direct` before `group`, then
   encounter order (assignment order, role before its ancestors, grant order
   within a role). Use a stable sort.
5. **Unconditional allow.** The first matching grant (in that order) with
   `condition: null` allows; report its permission and via. An unconditional
   grant always beats a conditional one, even a more specific one.
6. **Conditional grants.** If only conditional grants match:
   - with `record: null`, deny `record_required`;
   - otherwise evaluate each grant's condition in that order, skipping keys
     missing from `snapshot.conditions`. The first rule that is TRUE allows,
     reporting that grant's permission, via and condition key;
   - if none is TRUE, deny `condition_failed`.
7. Nothing matches: deny `no_permission`.

The rule context is:

- `record`: `request.record`.
- `user`: `bundle.attributes` with `"id"` set to `bundle.user_id`. The id
  wins, so an attribute named `id` can never spoof `user.id`.
- `tenant`: when the request scope has `tenant_id`, that tenant's attributes
  with `"id"` set to the tenant id (again the id wins); otherwise absent.

## `list_filter(snapshot, bundle, resource, action, scope, now)`

Apply steps 1 to 4. A failed membership check gives `none`. An unconditional
match gives `all`. Otherwise take the distinct condition keys of the matching
grants in match order, skip keys missing from the snapshot, and residualize
each rule for `user` and `tenant` (above):

- any residual `true` gives `all`;
- the `false` residuals are dropped; nothing left gives `none`;
- one residual left gives `filter` with that node; several give
  `filter` with `{"or": [node, ...]}` in that order.

## Record rules: three-valued and deny-safe

The full grammar and contract are in the `osiki/decision/rules.py` module
docstring. The parts SDK authors most often get wrong:

- Evaluation is three-valued: TRUE, FALSE, UNKNOWN. Only TRUE allows.
- A missing or `null` ref (absent field, absent record, absent tenant,
  missing attribute) makes its comparison UNKNOWN. A `null` literal does too,
  so `x eq null` and `x ne null` are both UNKNOWN.
- Values have type classes: boolean, number (integers and fractions compare
  numerically) and string. Comparing across classes is UNKNOWN: `true` never
  equals `1`, and `"1"` never equals `1`. Lists (except the right side of
  `in`) and objects are uncomparable, so any comparison with them is UNKNOWN.
- Ordering (`lt`, `lte`, `gt`, `gte`) works on numbers and strings (code
  point order). Ordering booleans is UNKNOWN.
- `x in [a, b]` is the Kleene OR of `x eq a`, `x eq b`: TRUE if one element
  equals, FALSE only if every element is comparable and none equals, otherwise
  UNKNOWN. A right side that is not a list is UNKNOWN.
- `and`, `or` and `not` use Kleene logic, and `not UNKNOWN` is UNKNOWN. So
  `not (record.team_id eq user.team_id)` is not TRUE when the field is
  missing.

Residual filter leaves are `{"field", "op", "value", "type"}`. `op` is one of
`eq ne lt lte gt gte in nin`, and `type` is the value's class (`string`,
`number`, `boolean`). A leaf matches a record only when the field is present,
non-null, of that type class and satisfies the op. `ne` and `nin` never match
a missing field.

How residuals are built (each point has a fixture in `filters/`):

- `user` and `tenant` refs are replaced by their values. A missing or `null`
  one makes that comparison UNKNOWN, which matches no record: after `not` is
  pushed down, an `or` drops it, an `and` holding it matches nothing, and on
  its own it gives `none`.
- A record ref on the right flips the operator: `100 lt record.amount` gives
  `amount gt 100`.
- `not` is pushed down to the leaves (De Morgan for `and` / `or`), negating
  each op: `eq`/`ne`, `lt`/`gte`, `lte`/`gt`. Output trees never contain
  `not`.
- `in` gives one `in` leaf per type class present in the list, in order of
  first appearance, ORed together; `null` elements are dropped.
- `nin` only comes from `not (x in [...])`. A list of one type class gives one
  `nin` leaf; a list mixing classes or holding `null` is UNKNOWN. `not (x in
  [])` holds for every comparable value, so it gives three `nin []` leaves,
  one per type class (`string`, `number`, `boolean`), ORed together.
