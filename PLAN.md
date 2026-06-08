# Plan — Role-Based Feature List & Task Flows

## Roles

| Role | How Created | Auth Source | Scope |
|------|-------------|-------------|-------|
| **Admin** | Environment variables (`ADMIN_USERNAME` / `ADMIN_PASSWORD`) | Env-var comparison | Platform-wide — manages all tenants |
| **Tenant** | Self-signup via `/signup` | `users` DB table (bcrypt) | Own tenant — bot settings, knowledge, users |
| **Invited User** | Invited by tenant via `/tenant/access/users/add` | `users` DB table (bcrypt) | Same tenant — chat + full tenant panel |

---

## Admin (Super-Admin)

### Features
- Login at `/tenant/login` with env-var credentials (`admin` / `admin123` by default)
- View all tenants in a table (ID, name, slug, status, created date)
- Create new tenants
- Edit tenant names
- Delete tenants (cascades users, settings, knowledge, curator data)
- Default tenant (ID=1) is protected from deletion

### Lifecycle
```
Admin comes to website
  → /tenant/login
  → enters env-var credentials
  → redirected to /tenant/tenants
  → manages tenants (create/list/edit/delete)
  → logout
```

### Sidebar
- **Tenants** — only item visible to admin

---

## Tenant

### Features
- Sign up at `/signup` (business name, email, password)
- Login at `/tenant/login` (email + password) **or** `/login` (email + password)
- Chat at `/` with the bot
- Profile icon in chat header links to tenant dashboard (`/tenant/`)
- Full tenant admin panel:

  | Page | URL | Purpose |
  |------|-----|---------|
  | Dashboard | `/tenant/` | Stats (URLs, docs), bot identity, rebuild index |
  | Bot Settings | `/tenant/settings` | Name, avatar, theme, language, personality, tone, purpose, instructions, LLM config |
  | Knowledge Base | `/tenant/knowledge` | Add/delete URLs, upload/delete documents, rebuild vector index |
  | Curator Queue | `/tenant/curator` | View & approve/dismiss content change detections, trigger scan |
  | Access | `/tenant/access` | View users, invite new users, delete users |
  | Change Password | `/change_password` | Update own password |

### Lifecycle
```
User comes to website
  → /signup
  → enters business name, email, password
  → account + tenant created
  → redirected to / (chat)
  → uses profile icon to go to /tenant/ dashboard
  → configures bot settings, knowledge, curator
  → invites users via Access page
  → logout
```

### Subsequent visits
```
User comes to website
  → /tenant/login (or /login)
  → enters email + password
  → redirected to /tenant/ (dashboard) or / (chat)
  → manages bot or chats
  → logout
```

---

## Invited User

### Features
- No signup — created by tenant via Access page
- Receives temporary password from the inviting tenant
- Login at `/login` (email + temp password) only
- Chat at `/` with the bot
- **Cannot access the tenant dashboard** — `/tenant/` routes are blocked
- Can change own password at `/change_password`

### Lifecycle
```
Tenant invites user via /tenant/access
  → enters email (optionally sets password, or auto-generated)
  → temporary password shown once

Invited user comes to website
  → /login
  → enters email + temporary password
  → redirected to / (chat)
  → chats with bot
  → changes password at /change_password  (optional)
  → logout
```

### Subsequent visits
```
User comes to website
  → /login
  → enters email + password
  → redirected to chat
  → chats, changes password
  → logout
```

---

## Summary Table

| Capability | Admin | Tenant | Invited User |
|---|---|---|---|
| Login at `/tenant/login` | ✅ (env-var) | ✅ (DB) | ✅ (DB) |
| Login at `/login` | ❌ | ✅ | ✅ |
| Chat at `/` | ❌ | ✅ | ✅ |
| View all tenants | ✅ | ❌ | ❌ |
| Create tenants | ✅ | ❌ | ❌ |
| Edit/delete any tenant | ✅ | ❌ | ❌ |
| Access tenant dashboard (`/tenant/`) | ❌ | ✅ | ❌ |
| Manage own bot settings | ❌ | ✅ | ❌ |
| Manage own knowledge base | ❌ | ✅ | ❌ |
| Manage curator queue | ❌ | ✅ | ❌ |
| View users in tenant | ❌ | ✅ | ❌ |
| Invite new users | ❌ | ✅ | ❌ |
| Delete users | ❌ | ✅ | ❌ |
| Change own password | ❌ | ✅ | ✅ |

> **Role values in DB:** `tenant` = tenant owner (full access), `member` = invited user (chat only).
> Invited users log in at `/login` and are restricted to the chat interface only.
