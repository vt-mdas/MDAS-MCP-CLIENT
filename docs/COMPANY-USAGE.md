# MDAS MCP

## What we built

MDAS MCP lets AI assistants call **existing WebAPI quote and fundamental endpoints** as **MCP tools** (e.g. level-1 quotes, option chains, company profile), using the **same MDAS accounts and entitlements** as the website—no separate API keys or manual token paste.

| Deliverable | Repository / location | Purpose |
|-------------|----------------------|---------|
| **MCP HTTP server** | `MDAS-MCP`, hosted on **AWS** | Exposes tools at `POST /mcp`; forwards `Authorization: Bearer` to WebAPI |
| **OAuth authorization server** | MDAS auth | Standard OAuth sign-in for MCP clients; issues the Bearer token |
| **Client setup** | [`MDAS-MCP-CLIENT`](https://github.com/vt-mdas/MDAS-MCP-CLIENT) | Docs and `mcp.json` example. No local software |

**Important:** The MCP server **does not store user tokens**. Cursor obtains tokens through OAuth, stores them, and sends them on every `/mcp` request.

---

## Environments

| Environment | MCP URL |
|-------------|---------|
| **staging** | `https://mdas-mcp-staging.viewtrade.dev/mcp` |
| **dev** | `https://mdas-mcp-dev.viewtrade.dev/mcp` |

---

## Architecture

```
┌──────────── Cursor (user PC) ────────────┐
│  "type": "http"  →  MCP URL              │
│  OAuth sign-in in browser, token stored  │
│  by Cursor                               │
└───────┬──────────────────────────────────┘
        │ HTTPS  Authorization: Bearer
        ▼
┌─────────────────── AWS ────────────────────┐
│  MDAS-MCP  —  POST /mcp  (Streamable HTTP) │
│  Stateless; calls WebAPI …/api/quote/…     │
└────────────────────────────────────────────┘
        │
        ▼
   WebAPI + OAuth server (MDAS auth & entitlements)
```

---

## Sign-in flow

1. User adds the MCP config (`"type": "http"` + MCP URL) to `mcp.json`. Cursor detects it automatically.
2. Cursor calls `/mcp`, gets **401**, and discovers the OAuth authorization server. The server shows under **Needs Attention** as *Needs authentication* with an **Authenticate** button.
3. User clicks **Authenticate**. Cursor opens the browser to the **MDAS login page** (OAuth authorize endpoint).
4. User signs in with MDAS credentials.
5. If the user has entitlements to sign, the browser redirects to the **entitlement signing page**.
6. After login, the browser is redirected back to Cursor with an authorization code, and Cursor exchanges it for tokens (see [How the token gets to Cursor](#how-the-token-gets-to-cursor)).
7. On success, Cursor sends `Authorization: Bearer` on every `/mcp` call and loads all tools. The server shows as **Connected**.
8. **Session expiry:**
   - **Access token expires, refresh still valid:** Cursor refreshes in the background. No user action is needed.
   - **Session revoked (single-session: login elsewhere) or refresh fails:** the server returns to *Needs authentication*. The user clicks **Authenticate** and the flow restarts at step 3.

### How the token gets to Cursor

The MDAS authorization server is built on **OpenIddict** and uses the standard OAuth 2.1 **authorization code + PKCE** flow. The server never pushes a token to Cursor; Cursor requests it.

| Step | Where | What happens |
|------|-------|--------------|
| 1. Discovery | Cursor → MDAS-MCP | `/mcp` returns **401**; Cursor reads the server metadata to find the authorization server's **authorize** and **token** endpoints. |
| 2. Authorize | Browser → OpenIddict | Cursor generates a secret **PKCE `code_verifier`** and opens the **authorize endpoint** with its hash (`code_challenge`), `client_id` and `redirect_uri`. |
| 3. Login + entitlements | Browser → MDAS pages | OpenIddict sends the user to the MDAS login page (`source=oauth`) and, if needed, the entitlement signing page. |
| 4. OAuth bridge (internal) | MDAS SPA → API | After login, the MDAS website (SPA) POSTs `return_url` and the MDAS `access_token` (body parameters) to `/connect/oauth-bridge`, which continues to the authorize endpoint. Users usually don't see this step. |
| 5. Callback | Browser → Cursor | The authorize endpoint redirects the browser to Cursor's `redirect_uri` with a short-lived, single-use **authorization code**. This is a code, not a token. |
| 6. Token exchange | Cursor → OpenIddict | Cursor posts the code **plus the original `code_verifier`** to the **token endpoint**. OpenIddict verifies it against the hash from step 2 and returns the **access token** in the response. |
| 7. Use | Cursor → MDAS-MCP | Cursor stores the tokens and sends `Authorization: Bearer <access_token>` on every `/mcp` call. |

**Why this is safe:** the token Cursor uses for MCP never passes through the browser. An intercepted authorization code is useless without the `code_verifier`, which only Cursor holds.

---

## Who does what

| Role | Responsibility |
|------|----------------|
| **Platform / MCP ops** | Deploy and monitor the hosted MDAS-MCP service per environment |
| **API / auth team** | OAuth server configuration: clients, redirect URIs, scopes, token lifetimes |
| **Frontend team** | MDAS login and entitlement signing pages, and the SPA's call to the OAuth bridge |
| **End user (Cursor)** | Add the MCP URL to `mcp.json`, click **Authenticate**, ask for data in chat |

---

## Using MCP in Cursor (internal quick start)

1. **Operators:** ensure hosted MCP and WebAPI are up for the target environment.
2. **User:** add the server to `~/.cursor/mcp.json` or `.cursor/mcp.json` (see [`examples/cursor-mcp.json.example`](../examples/cursor-mcp.json.example)).
3. **User:** in Cursor's MCP settings, click **Authenticate** and complete the browser sign-in (plus entitlement signing if prompted).
4. **Ask:** e.g. *“Get level 1 quotes for AAPL using the level1 tool.”*
5. **Generic equity quotes** use **`level1`**, not Polygon tools, unless the user asks for Polygon.

See [USER-MANUAL.md](USER-MANUAL.md) and [demo-prompts.md](demo-prompts.md).

---

## MCP tools (68 today)

The MCP server exposes **68 tools** today—all backed by existing WebAPI **quote**, **fundamental**, and **reformat** endpoints. After you connect **mdas-dev** or **mdas-staging** in Cursor, the full tool list appears in the MCP panel (names and descriptions update with each server release).

| Category | Count | Examples |
|----------|------:|----------|
| **Named shortcuts** | 3 | `level1`, `option_chain_dates`, `company_profile` |
| **Quote tools** | 42 | `quote_*` — equities, options, bonds, FX, international, night session, Polygon, charts, search, snapshots |
| **Fundamental tools** | 8 | `fund_*` — profile, screener filters, ETFs/ETNs, master file, option corporate actions, EOD |
| **Generic escape hatches** | 2 | `quote_endpoint`, `fundamental_endpoint` — any registered quote/fundamental path |
| **Reformat helpers** | 13 | `reformat_*` — same data, common display shapes (equity, option, bonds, FX, search, historical, etc.) |

### Roadmap — management API tools (planned)

Today MCP covers **market-data** quote and fundamental APIs only. **We plan to add MCP tools for all WebAPI management APIs**—e.g. user and session administration, firms, entitlements, permissions, integrations, logging, and other operator/admin endpoints—so assistants can perform the same management tasks allowed by a user’s JWT and role, not only market-data lookups. New tools will ship incrementally; this doc will be updated as each area is exposed.

---

## Troubleshooting (common)

| Symptom | Likely cause |
|---------|----------------|
| **405 Method Not Allowed** | URL is the bare host instead of `…/mcp` |
| Browser doesn't open after **Authenticate** | Toggle the server off/on in Cursor's MCP settings, or restart Cursor |
| Browser doesn't return to Cursor / Cursor doesn't connect | Cursor closed or not listening for the callback; click **Authenticate** again |
| Worked, then auth or tools fail / back to *Needs authentication* | Session revoked (single-session login elsewhere) or refresh failed; complete the browser sign-in again |
| Connected but empty tools | Wrong environment URL for the credentials used; or toggle the server off/on |
| Login page errors on redirect | Client redirect URI not registered on the OAuth server for that environment |
| Tool calls **polygon/snapshot** for “quote AAPL” | Ask explicitly for **`level1`**, or use updated tool descriptions (prefer `level1` for generic quotes) |
| Entitlement signing page loops | Signing not saved on the MDAS side; check with the frontend / auth team |

---

## Related documentation

| Document | Use |
|----------|-----|
| [USER-MANUAL.md](USER-MANUAL.md) | End-user setup, sign-in, and errors |
| [demo-prompts.md](demo-prompts.md) | Example prompts |
| [MDAS-MCP-CLIENT README](../README.md) | Client setup quick start |
| `MDAS-MCP/README.md` | Server deploy (operators) |

---

## Summary

We added **MCP access to MDAS market data** using **existing MDAS accounts and entitlements**: standard OAuth sign-in → **stateless MCP on AWS** — **68 quote and fundamental tools today**, with **all WebAPI management APIs planned as MCP tools** next. **Cursor users** only add the MCP URL (staging or dev) to `mcp.json` and click **Authenticate**; **operators** run the hosted **MDAS-MCP** service on AWS.
