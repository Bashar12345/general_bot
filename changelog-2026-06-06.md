# Changelog — 2026-06-06

## Files Modified

### Database
- **`db.py`**
  - Added `language TEXT DEFAULT 'en'` migration for `settings` table
  - Added `language TEXT DEFAULT 'en'` column to `settings` CREATE TABLE schema
  - Included `language` in the default settings insert row

### DTO
- **`api/dto.py`**
  - Added `language: str = "en"` field to `SettingsUpdateRequest`

### Admin Handler
- **`api/handlers/admin_handler.py`**
  - `update_settings()` now handles `language` field in DB update + insert
  - `get_context_vars()` now injects `admin_language` into all admin templates

### Admin Route
- **`admin.py`**
  - Added `DEFAULT_LANGUAGE`, `LANGUAGE_OPTIONS` (en, bn)
  - Settings form handler reads `language` from POST data
  - Settings template passed `language_options` and `bot_avatar_url`

---

### CSS — Complete Redesign

- **`static/admin.css`** — Major rewrite
  - Inter font via Google Fonts
  - New dark/light theme variable system (`--bg`, `--surface`, `--accent`, etc.)
  - Sidebar styles (`.sidebar`, `.brand`, `.nav-section`, `.nav-label`, `.logout-wrap`)
  - Icon support for sidebar and action buttons (`.icon-btn`, `.icon-btn.danger`)
  - Polished cards, stats grid, tables, forms (`.card`, `.stat`, `.form-row`, `.btn`, `.badge`)
  - Table responsiveness (`.table-wrap`, `.hash-cell`, `.filename-cell`)
  - `.form-row` vertical spacing fix (`margin-bottom: 20px`)
  - `.main > h1:first-child` heading spacing fix (`margin-bottom: 24px`)

- **`static/admin_login.css`** — Rewrite
  - Inter font
  - Login card layout with proper dark/light theme support

- **`static/auth.css`** — Rewrite
  - Inter font
  - Glassmorphism card, polished form elements, brand mark

- **`static/chat.css`** — Updated
  - Added Inter font import
  - Input uses Inter font family

---

### Templates — Redesign & Icons

- **`templates/admin/base.html`** — Sidebar redesign
  - Brand area with avatar and overlay handling
  - Inline SVG icons for every nav item (Dashboard, Tenants, Settings, Knowledge, Curator, Access, Logout)
  - Nav organized into sections (Main / Bot / Operations)
  - Active state highlighting with `active` class
  - `html lang` attribute reads from `admin_language`

- **`templates/admin/login.html`** — Polished layout
  - Card layout with brand mark, subtitle, "Sign In" heading
  - Uses new `admin_login.css` classes

- **`templates/admin/settings.html`** — Language support + cleanup
  - Added Language dropdown (English / বাংলা Bangla)
  - Replaced inline styles with `.form-row` / `.field` CSS classes
  - Shows current bot avatar in polished avatar circle

- **`templates/admin/knowledge.html`** — Responsive tables + icon buttons
  - URL table wrapped in `.table-wrap` for horizontal scroll
  - Doc tables (PDF, images, etc.) wrapped in `.table-wrap` via `doc_table` macro
  - Long filenames/URLs truncated with `.filename-cell`
  - Action buttons replaced with icon buttons (trash for delete, plus for add, upload icon, refresh for rebuild)

- **`templates/admin/tenants.html`** — Icon buttons
  - Edit/Delete actions replaced with pencil/trash icon buttons
  - "New Tenant" link uses plus icon + text

- **`templates/admin/access.html`** — Icon buttons
  - Save/Delete user actions replaced with checkmark/trash icon buttons
  - "Invite" button uses user-plus icon

- **`templates/admin/curator.html`** — Icon buttons + responsive table
  - "Apply update" replaced with check-circle icon
  - "View diff" replaced with eye icon
  - Recent Snapshots table uses `.hash-cell` for long hash truncation

- **`templates/admin/edit_tenant.html`** — Icon buttons
  - Save/Cancel buttons use checkmark/x icons

- **`templates/admin/dashboard.html`** — Rebuild button icon
  - "Rebuild Index Now" button has refresh icon

## New File
- **`changelog-2026-06-06.md`** — This file
