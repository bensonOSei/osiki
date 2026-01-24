## RBAC Management System - Schema Design Report

---

## Table of Contents

1. [Overview](#overview)
2. [Design Principles](#design-principles)
3. [Collections](#collections)
4. [Indexes](#indexes)
5. [Relationships](#relationships)
6. [Core Algorithms](#core-algorithms)
7. [Example Documents](#example-documents)
8. [Validation Rules](#validation-rules)

---

## Overview

This document defines the MongoDB schema for a multi-tenant, hierarchical RBAC (Role-Based Access Control) management system. The system supports:

- **Hierarchical roles** with unlimited depth inheritance
- **Flexible multi-tenant scoping** with subset-based matching
- **Group-based role assignments** for easier management
- **Constraint enforcement** (mutual exclusion, cardinality, prerequisites)
- **Comprehensive audit logging** for compliance
- **High-performance authorization** via Redis caching

---

## Design Principles

### 1. Soft Delete Strategy

| Collection | Strategy | Rationale |
|------------|----------|-----------|
| `users`, `groups`, `roles`, `permissions` | Soft delete (`is_active: false`) | Audit trails reference these entities; compliance requires historical data |
| `user_roles`, `user_groups`, `group_roles` | Soft delete | Assignment history is the audit trail |
| `constraints` | Soft delete | Historical constraint violations must be explainable |
| `audit_logs` | TTL hard delete (1-2 years) | High volume; retention limits apply |
| `access_logs` | TTL hard delete (30-90 days) | Extremely high volume; primarily for monitoring |

### 2. Permission Inheritance

**Direction**: Child roles inherit all permissions from ancestor roles.

```
viewer                    → { reports:read }
  └── editor              → { reports:read, reports:write }
        └── admin         → { reports:read, reports:write, reports:delete, users:manage }
```

More specific (deeper) roles are more privileged. Assigning `admin` automatically grants `viewer` and `editor` permissions.

### 3. Scope Matching

**Rule**: User scope must be a **subset** of request scope.

```
User Scope: { tenant_id: "fido_gh" }
Request:    { tenant_id: "fido_gh", branch_id: "accra" }
Result:     ✅ ALLOWED (user scope ⊆ request scope)

User Scope: { tenant_id: "fido_gh", branch_id: "accra" }
Request:    { tenant_id: "fido_gh", branch_id: "kumasi" }
Result:     ❌ DENIED (branch_id mismatch)

User Scope: {} (empty/null)
Request:    { anything }
Result:     ✅ ALLOWED (global access)
```

### 4. Access Logging Strategy

| Event Type | Logging Rate | Rationale |
|------------|--------------|-----------|
| Denials | 100% | Security critical; enables threat detection |
| Slow requests (>50ms) | 100% | Performance monitoring |
| Successful requests | 10% sampled | Analytics without storage explosion |

---

## Collections

### 1. `users`

Represents entities that can be assigned roles and permissions.

```javascript
{
  // Identity
  _id: ObjectId,
  external_id: String,                    // From auth provider (Auth0, Firebase, etc.)
  email: String,                          // Optional, for lookups
  
  // Attributes
  metadata: {
    display_name: String,
    department: String,
    employee_id: String,
    // ... extensible
  },
  
  // State
  is_active: Boolean,                     // Soft delete flag
  
  // Timestamps
  created_at: ISODate,
  updated_at: ISODate
}
```

**Field Details**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `_id` | ObjectId | Auto | Primary key |
| `external_id` | String | Yes | Unique identifier from external auth provider |
| `email` | String | No | User email, unique if provided |
| `metadata` | Object | No | Flexible key-value attributes |
| `is_active` | Boolean | Yes | `false` = soft deleted |
| `created_at` | ISODate | Yes | Document creation time |
| `updated_at` | ISODate | Yes | Last modification time |

---

### 2. `groups`

Logical groupings of users for bulk role assignment.

```javascript
{
  // Identity
  _id: ObjectId,
  name: String,                           // Unique group name
  description: String,
  
  // Attributes
  metadata: {
    department: String,
    cost_center: String,
    manager_id: String,
    // ... extensible
  },
  
  // State
  is_active: Boolean,
  
  // Timestamps
  created_at: ISODate,
  updated_at: ISODate
}
```

**Field Details**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `_id` | ObjectId | Auto | Primary key |
| `name` | String | Yes | Unique group identifier |
| `description` | String | No | Human-readable description |
| `metadata` | Object | No | Flexible attributes |
| `is_active` | Boolean | Yes | `false` = soft deleted |
| `created_at` | ISODate | Yes | Document creation time |
| `updated_at` | ISODate | Yes | Last modification time |

---

### 3. `roles`

Defines named collections of permissions with optional hierarchy.

```javascript
{
  // Identity
  _id: ObjectId,
  name: String,                           // Unique role name
  description: String,
  
  // Hierarchy
  parent_role_id: ObjectId | null,        // Reference to parent role (null = root)
  
  // Permissions
  permission_ids: [ObjectId],             // Direct permissions (not inherited)
  
  // Attributes
  metadata: {
    owner: String,                        // Team/person responsible for this role
    service: String,                      // Which service defined this role
    tags: [String],                       // Categorization tags
    // ... extensible
  },
  
  // Protection
  is_system: Boolean,                     // true = cannot be deleted or modified
  
  // State
  is_active: Boolean,
  
  // Timestamps
  created_at: ISODate,
  updated_at: ISODate
}
```

**Field Details**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `_id` | ObjectId | Auto | Primary key |
| `name` | String | Yes | Unique role identifier |
| `description` | String | No | Human-readable description |
| `parent_role_id` | ObjectId | No | Parent role for inheritance; `null` = root role |
| `permission_ids` | [ObjectId] | Yes | Array of permission references (can be empty) |
| `metadata` | Object | No | Flexible attributes |
| `is_system` | Boolean | Yes | Protected system roles cannot be modified |
| `is_active` | Boolean | Yes | `false` = soft deleted |
| `created_at` | ISODate | Yes | Document creation time |
| `updated_at` | ISODate | Yes | Last modification time |

**Hierarchy Rules**:
- A role with `parent_role_id: null` is a root role
- Circular references are forbidden (enforced in application)
- No maximum depth limit
- Deleting a parent role requires reassigning or deleting children first

---

### 4. `permissions`

Atomic permission definitions representing resource-action pairs.

```javascript
{
  // Identity
  _id: ObjectId,
  resource: String,                       // e.g., "invoices", "users", "reports"
  action: String,                         // e.g., "read", "write", "delete", "admin"
  
  // Description
  description: String,
  
  // Attributes
  metadata: {
    service: String,                      // Owning service
    category: String,                     // UI grouping
    risk_level: String,                   // "low", "medium", "high", "critical"
    // ... extensible
  },
  
  // State
  is_active: Boolean,
  
  // Timestamps
  created_at: ISODate
}
```

**Field Details**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `_id` | ObjectId | Auto | Primary key |
| `resource` | String | Yes | Resource identifier |
| `action` | String | Yes | Action identifier |
| `description` | String | No | Human-readable description |
| `metadata` | Object | No | Flexible attributes |
| `is_active` | Boolean | Yes | `false` = soft deleted |
| `created_at` | ISODate | Yes | Document creation time |

**Permission String Format**: `{resource}:{action}`

**Wildcard Support** (application-level):
- `invoices:*` — All actions on invoices resource
- `*:read` — Read action on all resources
- `*:*` — Superadmin (all permissions)

**Reserved Actions**:
| Action | Meaning |
|--------|---------|
| `read` | View/list resources |
| `write` | Create/update resources |
| `delete` | Remove resources |
| `admin` | Full control including configuration |
| `*` | Wildcard (all actions) |

---

### 5. `user_roles`

Junction collection linking users to roles with scope and metadata.

```javascript
{
  // Identity
  _id: ObjectId,
  
  // Relationship
  user_id: ObjectId,                      // Reference to users collection
  role_id: ObjectId,                      // Reference to roles collection
  
  // Scope (flexible multi-tenancy)
  scope: {
    tenant_id: String,
    region: String,
    branch_id: String,
    department: String,
    // ... any keys
  },
  
  // Assignment metadata (audit trail)
  assigned_by: String,                    // User ID or "system"
  assigned_at: ISODate,
  expires_at: ISODate | null,             // Optional expiration
  assignment_reason: String,              // Optional justification
  
  // State
  is_active: Boolean,
  
  // Timestamps
  created_at: ISODate,
  updated_at: ISODate
}
```

**Field Details**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `_id` | ObjectId | Auto | Primary key |
| `user_id` | ObjectId | Yes | Reference to user |
| `role_id` | ObjectId | Yes | Reference to role |
| `scope` | Object | Yes | Scope restriction; `{}` = global |
| `assigned_by` | String | Yes | Who made this assignment |
| `assigned_at` | ISODate | Yes | When assignment was made |
| `expires_at` | ISODate | No | Auto-revoke after this time |
| `assignment_reason` | String | No | Justification for audit |
| `is_active` | Boolean | Yes | `false` = revoked |
| `created_at` | ISODate | Yes | Document creation time |
| `updated_at` | ISODate | Yes | Last modification time |

**Uniqueness**: Combination of `(user_id, role_id, scope)` should be unique when `is_active: true`.

---

### 6. `user_groups`

Junction collection linking users to groups.

```javascript
{
  // Identity
  _id: ObjectId,
  
  // Relationship
  user_id: ObjectId,                      // Reference to users collection
  group_id: ObjectId,                     // Reference to groups collection
  
  // Membership metadata
  added_by: String,                       // User ID or "system"
  added_at: ISODate,
  membership_type: String,                // "member", "admin", "owner" (optional)
  
  // State
  is_active: Boolean,
  
  // Timestamps
  created_at: ISODate,
  updated_at: ISODate
}
```

**Field Details**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `_id` | ObjectId | Auto | Primary key |
| `user_id` | ObjectId | Yes | Reference to user |
| `group_id` | ObjectId | Yes | Reference to group |
| `added_by` | String | Yes | Who added user to group |
| `added_at` | ISODate | Yes | When user was added |
| `membership_type` | String | No | Role within the group |
| `is_active` | Boolean | Yes | `false` = removed from group |
| `created_at` | ISODate | Yes | Document creation time |
| `updated_at` | ISODate | Yes | Last modification time |

**Uniqueness**: Combination of `(user_id, group_id)` should be unique when `is_active: true`.

---

### 7. `group_roles`

Junction collection linking groups to roles with scope.

```javascript
{
  // Identity
  _id: ObjectId,
  
  // Relationship
  group_id: ObjectId,                     // Reference to groups collection
  role_id: ObjectId,                      // Reference to roles collection
  
  // Scope (same structure as user_roles)
  scope: {
    tenant_id: String,
    region: String,
    branch_id: String,
    // ... any keys
  },
  
  // Assignment metadata
  assigned_by: String,
  assigned_at: ISODate,
  expires_at: ISODate | null,
  assignment_reason: String,
  
  // State
  is_active: Boolean,
  
  // Timestamps
  created_at: ISODate,
  updated_at: ISODate
}
```

**Field Details**: Same as `user_roles` but with `group_id` instead of `user_id`.

---

### 8. `constraints`

Business rules that restrict role assignments.

```javascript
{
  // Identity
  _id: ObjectId,
  name: String,                           // Human-readable constraint name
  description: String,
  
  // Constraint definition
  type: String,                           // "mutual_exclusion" | "cardinality" | "prerequisite"
  
  config: {
    // === For mutual_exclusion ===
    role_ids: [ObjectId],                 // Roles that cannot be held together
    
    // === For cardinality ===
    role_id: ObjectId,                    // Target role
    max_assignments: Number,              // Maximum number of assignments
    scope_level: String,                  // "global" | "per_tenant" | "per_scope"
    
    // === For prerequisite ===
    role_id: ObjectId,                    // Role that requires prerequisite
    requires_role_id: ObjectId,           // Required role
  },
  
  // State
  is_active: Boolean,
  
  // Timestamps
  created_at: ISODate,
  updated_at: ISODate
}
```

**Constraint Types**:

| Type | Description | Example |
|------|-------------|---------|
| `mutual_exclusion` | User cannot hold these roles simultaneously | Payment initiator and payment approver |
| `cardinality` | Limits number of users with this role | Max 3 super_admins globally |
| `prerequisite` | Must have role A before getting role B | Must be `employee` before `manager` |

**Scope Level for Cardinality**:

| Level | Meaning |
|-------|---------|
| `global` | Max N assignments across entire system |
| `per_tenant` | Max N assignments per tenant_id |
| `per_scope` | Max N assignments per exact scope match |

---

### 9. `audit_logs`

Immutable record of all administrative actions.

```javascript
{
  // Identity
  _id: ObjectId,
  
  // When
  timestamp: ISODate,
  
  // Who
  actor_id: String,                       // User ID, "system", or API key ID
  actor_type: String,                     // "user" | "system" | "api_key"
  
  // What
  action: String,                         // Action identifier (see table below)
  
  // Target
  target_type: String,                    // "user" | "role" | "permission" | "group" | "constraint"
  target_id: String,                      // ID of affected entity
  
  // Changes
  changes: {
    before: Object | null,                // State before change (null for creates)
    after: Object | null,                 // State after change (null for deletes)
  },
  
  // Context
  context: {
    ip_address: String,
    user_agent: String,
    request_id: String,                   // Correlation ID
    service: String,                      // Originating service
    scope: Object,                        // Tenant context if applicable
  }
}
```

**Action Types**:

| Action | Description |
|--------|-------------|
| `user.created` | New user registered |
| `user.updated` | User metadata modified |
| `user.deactivated` | User soft deleted |
| `user.reactivated` | User restored |
| `role.created` | New role defined |
| `role.updated` | Role modified |
| `role.deactivated` | Role soft deleted |
| `role.permission_added` | Permission added to role |
| `role.permission_removed` | Permission removed from role |
| `role.parent_changed` | Role hierarchy modified |
| `permission.created` | New permission defined |
| `permission.deactivated` | Permission soft deleted |
| `user_role.assigned` | Role assigned to user |
| `user_role.revoked` | Role removed from user |
| `user_role.expired` | Role auto-expired |
| `group.created` | New group created |
| `group.updated` | Group modified |
| `group.deactivated` | Group soft deleted |
| `group_role.assigned` | Role assigned to group |
| `group_role.revoked` | Role removed from group |
| `user_group.added` | User added to group |
| `user_group.removed` | User removed from group |
| `constraint.created` | New constraint defined |
| `constraint.deactivated` | Constraint removed |
| `constraint.violated` | Assignment blocked by constraint |

**TTL**: Documents automatically deleted after 730 days (2 years).

---

### 10. `access_logs`

Record of authorization check requests and results.

```javascript
{
  // Identity
  _id: ObjectId,
  
  // When
  timestamp: ISODate,
  
  // Request
  user_id: String,                        // User being checked
  resource: String,                       // Requested resource
  action: String,                         // Requested action
  scope: Object,                          // Request scope/context
  
  // Result
  allowed: Boolean,                       // Authorization decision
  matched_permission: String | null,      // e.g., "invoices:write"
  matched_via: String | null,             // e.g., "role:finance_admin" or "group:finance_team"
  denial_reason: String | null,           // If denied: "no_permission" | "scope_mismatch" | "user_inactive"
  
  // Performance
  latency_ms: Number,                     // Processing time
  cache_hit: Boolean,                     // Whether result came from cache
  
  // Context
  context: {
    request_id: String,                   // Correlation ID
    service: String,                      // Requesting service
    ip_address: String,
  }
}
```

**Denial Reasons**:

| Reason | Description |
|--------|-------------|
| `no_permission` | User has no matching permission |
| `scope_mismatch` | User has permission but not for requested scope |
| `user_inactive` | User is deactivated |
| `role_inactive` | Matched role is deactivated |
| `assignment_expired` | Role assignment has expired |

**Logging Rules**:
- All denials: 100% logged
- Slow requests (>50ms): 100% logged
- Successful requests: 10% sampled

**TTL**: Documents automatically deleted after 90 days.

---

## Indexes

### `users`

```javascript
// Unique lookups
{ external_id: 1 }, { unique: true }
{ email: 1 }, { unique: true, sparse: true }

// Listing/filtering
{ is_active: 1, created_at: -1 }
```

### `groups`

```javascript
// Unique lookups
{ name: 1 }, { unique: true }

// Listing
{ is_active: 1, created_at: -1 }
```

### `roles`

```javascript
// Unique lookups
{ name: 1 }, { unique: true }

// Hierarchy traversal
{ parent_role_id: 1 }

// Permission lookups
{ permission_ids: 1 }

// Listing
{ is_active: 1, created_at: -1 }
```

### `permissions`

```javascript
// Unique resource:action pair
{ resource: 1, action: 1 }, { unique: true }

// Filtering
{ resource: 1 }
{ "metadata.service": 1 }
{ is_active: 1 }
```

### `user_roles`

```javascript
// Prevent duplicate active assignments
{ user_id: 1, role_id: 1, "scope.tenant_id": 1, is_active: 1 }, { unique: true, sparse: true }

// Get user's roles
{ user_id: 1, is_active: 1 }

// Get users with specific role
{ role_id: 1, is_active: 1 }

// Tenant-scoped queries
{ "scope.tenant_id": 1, role_id: 1, is_active: 1 }

// Expiration processing
{ expires_at: 1 }, { sparse: true }
```

### `user_groups`

```javascript
// Prevent duplicate memberships
{ user_id: 1, group_id: 1, is_active: 1 }, { unique: true, sparse: true }

// Get user's groups
{ user_id: 1, is_active: 1 }

// Get group members
{ group_id: 1, is_active: 1 }
```

### `group_roles`

```javascript
// Prevent duplicate assignments
{ group_id: 1, role_id: 1, "scope.tenant_id": 1, is_active: 1 }, { unique: true, sparse: true }

// Get group's roles
{ group_id: 1, is_active: 1 }

// Get groups with specific role
{ role_id: 1, is_active: 1 }
```

### `constraints`

```javascript
// Find constraints by type
{ type: 1, is_active: 1 }

// Find constraints involving specific role
{ "config.role_ids": 1 }
{ "config.role_id": 1 }
{ "config.requires_role_id": 1 }
```

### `audit_logs`

```javascript
// Recent logs
{ timestamp: -1 }

// Actor's activity
{ actor_id: 1, timestamp: -1 }

// Entity history
{ target_type: 1, target_id: 1, timestamp: -1 }

// Action filtering
{ action: 1, timestamp: -1 }

// TTL (auto-delete after 2 years)
{ timestamp: 1 }, { expireAfterSeconds: 63072000 }
```

### `access_logs`

```javascript
// Recent logs
{ timestamp: -1 }

// User's access history
{ user_id: 1, timestamp: -1 }

// Denial monitoring
{ allowed: 1, timestamp: -1 }

// Resource access patterns
{ resource: 1, action: 1, timestamp: -1 }

// TTL (auto-delete after 90 days)
{ timestamp: 1 }, { expireAfterSeconds: 7776000 }
```

---

## Relationships

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ENTITY RELATIONSHIPS                           │
└─────────────────────────────────────────────────────────────────────────────┘

                                    ┌──────────────┐
                                    │  permissions │
                                    │              │
                                    │  resource    │
                                    │  action      │
                                    └──────┬───────┘
                                           │
                                           │ permission_ids[]
                                           ▼
┌──────────────┐                    ┌──────────────┐
│    users     │                    │    roles     │
│              │                    │              │
│  external_id │                    │  name        │
│  email       │                    │  parent_id ──┼──► (self-reference)
│  metadata    │                    │  permission_ │
└──────┬───────┘                    │    ids[]     │
       │                            └──────┬───────┘
       │                                   │
       │    ┌──────────────┐               │
       │    │    groups    │               │
       │    │              │               │
       │    │  name        │               │
       │    │  description │               │
       │    └──────┬───────┘               │
       │           │                       │
       │           │                       │
       ▼           ▼                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                        JUNCTION TABLES                           │
├──────────────────┬──────────────────┬──────────────────┬─────────┤
│    user_roles    │   user_groups    │   group_roles    │         │
│                  │                  │                  │         │
│  user_id ────────┼──► users         │  group_id ───────┼──► groups
│  role_id ────────┼──────────────────┼──► roles         │         │
│  scope {}        │  user_id ────────┼──► users         │         │
│  assigned_by     │  group_id ───────┼──► groups        │  role_id ┼──► roles
│  assigned_at     │  added_by        │  scope {}        │         │
│  expires_at      │  added_at        │  assigned_by     │         │
└──────────────────┴──────────────────┴──────────────────┴─────────┘

┌──────────────────────────────────────────────────────────────────┐
│                      SUPPORTING TABLES                           │
├──────────────────┬──────────────────┬────────────────────────────┤
│   constraints    │   audit_logs     │      access_logs           │
│                  │                  │                            │
│  type            │  actor_id        │  user_id                   │
│  config {}       │  action          │  resource                  │
│                  │  target_type     │  action                    │
│                  │  target_id       │  allowed                   │
│                  │  changes {}      │  latency_ms                │
└──────────────────┴──────────────────┴────────────────────────────┘
```

---

## Core Algorithms

### 1. Permission Resolution

```python
async def get_effective_permissions(
    user_id: str, 
    scope: dict | None = None
) -> set[str]:
    """
    Get all permissions a user has, considering:
    1. Direct role assignments
    2. Roles via group membership
    3. Role hierarchy inheritance
    4. Scope filtering
    """
    permissions = set()
    
    # Step 1: Get user's direct role assignments
    direct_assignments = await user_roles_collection.find({
        "user_id": ObjectId(user_id),
        "is_active": True,
        "$or": [
            {"expires_at": None},
            {"expires_at": {"$gt": datetime.utcnow()}}
        ]
    }).to_list()
    
    # Step 2: Get user's groups
    user_groups = await user_groups_collection.find({
        "user_id": ObjectId(user_id),
        "is_active": True
    }).to_list()
    
    group_ids = [ug["group_id"] for ug in user_groups]
    
    # Step 3: Get role assignments via groups
    group_assignments = await group_roles_collection.find({
        "group_id": {"$in": group_ids},
        "is_active": True,
        "$or": [
            {"expires_at": None},
            {"expires_at": {"$gt": datetime.utcnow()}}
        ]
    }).to_list()
    
    # Step 4: Combine all assignments
    all_assignments = direct_assignments + group_assignments
    
    # Step 5: Filter by scope
    if scope:
        all_assignments = [
            a for a in all_assignments 
            if scope_matches(a.get("scope", {}), scope)
        ]
    
    # Step 6: Expand role hierarchy and collect permissions
    for assignment in all_assignments:
        role_ids = await get_role_with_ancestors(assignment["role_id"])
        
        for role_id in role_ids:
            role = await roles_collection.find_one({
                "_id": role_id,
                "is_active": True
            })
            
            if role:
                for perm_id in role.get("permission_ids", []):
                    permission = await permissions_collection.find_one({
                        "_id": perm_id,
                        "is_active": True
                    })
                    if permission:
                        permissions.add(f"{permission['resource']}:{permission['action']}")
    
    return permissions
```

### 2. Role Hierarchy Traversal

```python
async def get_role_with_ancestors(role_id: ObjectId) -> list[ObjectId]:
    """
    Get a role and all its ancestors (walking up the hierarchy).
    Returns list ordered from input role to root.
    
    Includes cycle detection.
    """
    ancestors = []
    visited = set()
    current_id = role_id
    
    while current_id:
        # Cycle detection
        if current_id in visited:
            raise ValueError(f"Circular role hierarchy detected at {current_id}")
        
        visited.add(current_id)
        ancestors.append(current_id)
        
        role = await roles_collection.find_one({"_id": current_id})
        if not role:
            break
            
        current_id = role.get("parent_role_id")
    
    return ancestors
```

### 3. Scope Matching

```python
def scope_matches(user_scope: dict | None, request_scope: dict) -> bool:
    """
    Check if user's scope allows access to requested scope.
    
    Rule: User scope must be a SUBSET of request scope.
    - Empty user scope = global access (matches everything)
    - Every key in user_scope must exist in request_scope with same value
    """
    # Empty or None scope = global access
    if not user_scope:
        return True
    
    for key, value in user_scope.items():
        if key not in request_scope:
            return False
        if request_scope[key] != value:
            return False
    
    return True
```

### 4. Authorization Check

```python
async def authorize(
    user_id: str,
    resource: str,
    action: str,
    scope: dict | None = None
) -> AuthorizationResult:
    """
    Main authorization check.
    
    Returns detailed result including:
    - allowed: bool
    - matched_permission: str | None
    - matched_via: str | None
    - denial_reason: str | None
    """
    # Check cache first
    cache_key = f"rbac:user:{user_id}:permissions:{hash_scope(scope)}"
    cached_permissions = await redis.get(cache_key)
    
    if cached_permissions:
        permissions = json.loads(cached_permissions)
        cache_hit = True
    else:
        permissions = await get_effective_permissions(user_id, scope)
        await redis.setex(cache_key, 300, json.dumps(list(permissions)))  # 5 min TTL
        cache_hit = False
    
    # Check for exact match
    required_permission = f"{resource}:{action}"
    if required_permission in permissions:
        return AuthorizationResult(
            allowed=True,
            matched_permission=required_permission,
            cache_hit=cache_hit
        )
    
    # Check for wildcard matches
    wildcards = [
        f"{resource}:*",    # All actions on resource
        f"*:{action}",      # Action on all resources
        "*:*"               # Superadmin
    ]
    
    for wildcard in wildcards:
        if wildcard in permissions:
            return AuthorizationResult(
                allowed=True,
                matched_permission=wildcard,
                cache_hit=cache_hit
            )
    
    return AuthorizationResult(
        allowed=False,
        denial_reason="no_permission",
        cache_hit=cache_hit
    )
```

### 5. Constraint Validation

```python
async def validate_constraints(
    user_id: str,
    role_id: ObjectId,
    scope: dict
) -> ConstraintValidationResult:
    """
    Validate all constraints before allowing role assignment.
    """
    constraints = await constraints_collection.find({
        "is_active": True
    }).to_list()
    
    for constraint in constraints:
        if constraint["type"] == "mutual_exclusion":
            if await check_mutual_exclusion_violated(user_id, role_id, constraint):
                return ConstraintValidationResult(
                    valid=False,
                    constraint_name=constraint["name"],
                    reason="User already has a mutually exclusive role"
                )
        
        elif constraint["type"] == "cardinality":
            if await check_cardinality_violated(role_id, scope, constraint):
                return ConstraintValidationResult(
                    valid=False,
                    constraint_name=constraint["name"],
                    reason=f"Maximum {constraint['config']['max_assignments']} assignments reached"
                )
        
        elif constraint["type"] == "prerequisite":
            if await check_prerequisite_missing(user_id, role_id, constraint):
                return ConstraintValidationResult(
                    valid=False,
                    constraint_name=constraint["name"],
                    reason="Prerequisite role not assigned"
                )
    
    return ConstraintValidationResult(valid=True)
```

---

## Example Documents

### User

```javascript
{
  _id: ObjectId("507f1f77bcf86cd799439011"),
  external_id: "auth0|61f7b2c3d4e5f6a7b8c9d0e1",
  email: "benson@fido.com",
  metadata: {
    display_name: "Benson Kwame",
    department: "Engineering",
    employee_id: "EMP-001"
  },
  is_active: true,
  created_at: ISODate("2024-01-15T10:30:00Z"),
  updated_at: ISODate("2024-01-15T10:30:00Z")
}
```

### Role Hierarchy

```javascript
// Root role
{
  _id: ObjectId("607f1f77bcf86cd799439001"),
  name: "viewer",
  description: "Basic read-only access",
  parent_role_id: null,
  permission_ids: [
    ObjectId("707f1f77bcf86cd799439001")  // reports:read
  ],
  metadata: { owner: "platform-team" },
  is_system: false,
  is_active: true,
  created_at: ISODate("2024-01-01T00:00:00Z"),
  updated_at: ISODate("2024-01-01T00:00:00Z")
}

// Child role
{
  _id: ObjectId("607f1f77bcf86cd799439002"),
  name: "editor",
  description: "Can view and edit",
  parent_role_id: ObjectId("607f1f77bcf86cd799439001"),  // inherits from viewer
  permission_ids: [
    ObjectId("707f1f77bcf86cd799439002")  // reports:write
  ],
  metadata: { owner: "platform-team" },
  is_system: false,
  is_active: true,
  created_at: ISODate("2024-01-01T00:00:00Z"),
  updated_at: ISODate("2024-01-01T00:00:00Z")
}

// Grandchild role
{
  _id: ObjectId("607f1f77bcf86cd799439003"),
  name: "admin",
  description: "Full administrative access",
  parent_role_id: ObjectId("607f1f77bcf86cd799439002"),  // inherits from editor
  permission_ids: [
    ObjectId("707f1f77bcf86cd799439003"),  // reports:delete
    ObjectId("707f1f77bcf86cd799439004")   // users:manage
  ],
  metadata: { owner: "platform-team" },
  is_system: true,
  is_active: true,
  created_at: ISODate("2024-01-01T00:00:00Z"),
  updated_at: ISODate("2024-01-01T00:00:00Z")
}

// Effective permissions for "admin" role:
// - reports:read    (inherited from viewer)
// - reports:write   (inherited from editor)
// - reports:delete  (direct)
// - users:manage    (direct)
```

### Scoped User Role Assignment

```javascript
{
  _id: ObjectId("807f1f77bcf86cd799439001"),
  user_id: ObjectId("507f1f77bcf86cd799439011"),
  role_id: ObjectId("607f1f77bcf86cd799439003"),  // admin
  scope: {
    tenant_id: "fido_gh",
    branch_id: "accra_main"
  },
  assigned_by: "admin_user_123",
  assigned_at: ISODate("2024-01-20T14:00:00Z"),
  expires_at: null,
  assignment_reason: "Promoted to branch admin",
  is_active: true,
  created_at: ISODate("2024-01-20T14:00:00Z"),
  updated_at: ISODate("2024-01-20T14:00:00Z")
}
```

### Mutual Exclusion Constraint

```javascript
{
  _id: ObjectId("907f1f77bcf86cd799439001"),
  name: "payment_separation_of_duties",
  description: "Users cannot both initiate and approve payments",
  type: "mutual_exclusion",
  config: {
    role_ids: [
      ObjectId("607f1f77bcf86cd799439010"),  // payment_initiator
      ObjectId("607f1f77bcf86cd799439011")   // payment_approver
    ]
  },
  is_active: true,
  created_at: ISODate("2024-01-01T00:00:00Z"),
  updated_at: ISODate("2024-01-01T00:00:00Z")
}
```

### Audit Log Entry

```javascript
{
  _id: ObjectId("a07f1f77bcf86cd799439001"),
  timestamp: ISODate("2024-01-20T14:00:00Z"),
  actor_id: "admin_user_123",
  actor_type: "user",
  action: "user_role.assigned",
  target_type: "user",
  target_id: "507f1f77bcf86cd799439011",
  changes: {
    before: null,
    after: {
      role_id: "607f1f77bcf86cd799439003",
      role_name: "admin",
      scope: { tenant_id: "fido_gh", branch_id: "accra_main" }
    }
  },
  context: {
    ip_address: "192.168.1.100",
    user_agent: "Mozilla/5.0...",
    request_id: "req_abc123",
    service: "admin-dashboard"
  }
}
```

### Access Log Entry

```javascript
{
  _id: ObjectId("b07f1f77bcf86cd799439001"),
  timestamp: ISODate("2024-01-20T15:30:00Z"),
  user_id: "507f1f77bcf86cd799439011",
  resource: "invoices",
  action: "write",
  scope: { tenant_id: "fido_gh", branch_id: "accra_main" },
  allowed: true,
  matched_permission: "invoices:write",
  matched_via: "role:finance_admin",
  denial_reason: null,
  latency_ms: 3.2,
  cache_hit: true,
  context: {
    request_id: "req_xyz789",
    service: "invoice-service",
    ip_address: "192.168.1.50"
  }
}
```

---

## Validation Rules

### Entity Validation

| Entity | Rule |
|--------|------|
| `users.external_id` | Required, unique, immutable after creation |
| `users.email` | Valid email format if provided, unique |
| `groups.name` | Required, unique, 1-100 characters |
| `roles.name` | Required, unique, 1-100 characters |
| `roles.parent_role_id` | Must reference existing active role; no cycles |
| `permissions.resource` | Required, 1-100 characters, alphanumeric + underscore |
| `permissions.action` | Required, 1-50 characters, alphanumeric + underscore |
| `permissions` (compound) | `resource` + `action` must be unique |

### Assignment Validation

| Rule | Description |
|------|-------------|
| Active target | Cannot assign inactive role/group |
| Active user | Cannot assign role to inactive user |
| Duplicate check | Same user+role+scope combination cannot exist twice (when active) |
| Constraint check | All active constraints must pass before assignment |
| Scope format | Scope keys must be strings; values must be strings |

### Hierarchy Validation

| Rule | Description |
|------|-------------|
| No cycles | Role cannot be its own ancestor |
| No orphans on delete | Cannot deactivate role with active children |
| Max depth (soft) | Warning if hierarchy exceeds 10 levels |

---

## Cache Strategy

### Redis Key Patterns

```
rbac:user:{user_id}:permissions                    → Set of all permission strings
rbac:user:{user_id}:permissions:{scope_hash}       → Scoped permissions
rbac:role:{role_id}:ancestors                      → Ordered list of ancestor role IDs
rbac:role:{role_id}:permissions                    → Set of permission strings for role
```

### TTLs

| Key Pattern | TTL | Rationale |
|-------------|-----|-----------|
| User permissions | 5 minutes | Balance between freshness and performance |
| Role ancestors | 1 hour | Hierarchy changes rarely |
| Role permissions | 10 minutes | Moderate change frequency |

### Invalidation Triggers

| Event | Invalidate |
|-------|------------|
| Role assigned/revoked for user | `rbac:user:{user_id}:*` |
| User added/removed from group | `rbac:user:{user_id}:*` |
| Permission added/removed from role | `rbac:role:{role_id}:*` + all users with role |
| Role hierarchy changed | `rbac:role:{role_id}:ancestors` + all descendant roles + all users with affected roles |
| Role deactivated | All related caches |

---

This completes the schema design. Ready to start implementing Phase 1?