# MDAS MCP

## What we built

MDAS MCP lets AI assistants call **existing WebAPI quote and fundamental endpoints** as **MCP tools** (e.g. level-1 quotes, option chains, company profile), using the **same JWT sessions** as the MDAS website—no separate API keys or manual token paste.

| Deliverable | Repository / location | Purpose |
|-------------|----------------------|---------|
| **MCP HTTP server** | [`MDAS-MCP`](../../) — `server.py` in Docker on **AWS** (or locally on port **8000**) | Exposes tools at `POST /mcp`; forwards `Authorization: Bearer` to WebAPI |
| **Stdio proxy (MCP host)** | [`MDAS-MCP-Client`](../../../MDAS-MCP-Client/) — `mcp_stdio_proxy.py` on the **user’s PC** | Cursor-compatible bridge: browser login, token file, stdio ↔ MCP HTTP |
| **WebAPI handoff** | `WebAPI-Server` — `POST /api/user/handoff/mint` and `…/exchange` | Website mints a one-time code; host exchanges it for login-shaped tokens |
| **Website integration** | MDAS SPA (`mdas-app-dev`) | Login with `?source=mcp`, mint after login, redirect to allowlisted callback |

**Important:** The MCP server **does not store user tokens**. The **stdio proxy** (or another MCP host) stores tokens locally and sends them on every `/mcp` request.

---

## Architecture (two processes)

```
┌──────────────── Cursor (user PC) ─────────────────┐
│  Cursor  ←stdio→  mcp_stdio_proxy.py              │
│       │ opens browser, listens 127.0.0.1:9847     │
│       │ tokens: %LOCALAPPDATA%\.mdas-mcp\         │
└───────┼───────────────────────────────────────────┘
        │ HTTPS  Authorization: Bearer + X-MDAS-*
        ▼
┌──────────────── AWS (or local Docker) ────────────┐
│  server.py  —  POST /mcp  (Streamable HTTP)       │
│  Stateless; calls mdas-api-dev …/api/quote/…      │
└───────────────────────────────────────────────────┘
        │
        ▼
   WebAPI + website (existing MDAS auth & entitlements)
```

| Port / URL | Component |
|------------|-----------|
| **`http://127.0.0.1:9847/callback`** | Proxy handoff listener (browser lands here after website mint)—**not** the MCP server |
| **`http://localhost:8000/mcp`** (local) or **`https://mdas-mcp-dev…/mcp`** (AWS) | MCP HTTP transport |
| **`https://mdas-api-dev.viewtrade.dev`** | WebAPI (login, handoff, quotes) |
| **`https://mdas-app-dev.viewtrade.dev/login?source=mcp`** | Website login for MCP |

---

## Sign-in flow (once per machine, or when tokens expire)

1. User enables **mdas-local** in Cursor (stdio + proxy).
2. Proxy opens the **website** with `?source=mcp` and `redirect_uri=http://127.0.0.1:9847/callback`.
3. User logs in (and completes **agreements** on the website if required).
4. SPA calls **`handoff/mint`**, then redirects the browser to **9847** with `code` + `state`.
5. Proxy calls **`handoff/exchange`**, saves **`access_token`** / **`refresh_token`** locally.
6. Proxy bridges Cursor ↔ MCP HTTP with Bearer on every tool call.
7. If access expires, MCP may refresh via WebAPI; if refresh fails, proxy can **re-open the browser** automatically.

API **`McpHandoff:AllowedRedirectUris`** must include **`http://127.0.0.1:9847/callback`** (already configured for dev).

---

## Who does what

| Role | Responsibility |
|------|----------------|
| **Platform / MCP ops** | Deploy `server.py` to AWS; health check `/health`; per-env `config.json`; allowlist hosted callback URLs if needed |
| **API team** | Handoff mint/exchange, `McpHandoff` config, session/refresh behavior |
| **Frontend team** | MCP login UX: `?source=mcp`, post-login **mint**, redirect to `redirect_url` |
| **End user (Cursor)** | Install **MDAS-MCP-Client**, add MCP config, sign in once, ask for quotes in chat |
| **Internal developer (local MCP)** | Optional: `docker compose up` in `MDAS-MCP/application` for MCP on **8000**; still use proxy for Cursor |

---

## Local development vs AWS

| | **Local dev** | **AWS (target for shared use)** |
|--|---------------|----------------------------------|
| MCP HTTP | Docker `localhost:8000` | `https://mdas-mcp-dev.viewtrade.dev/mcp` |
| Proxy | Same on each developer PC | Same on each user PC |
| Cursor config | `.cursor/mcp.json` → `mcp_stdio_proxy.py` + `MDAS_MCP_HTTP_URL` | Point `MDAS_MCP_HTTP_URL` at **AWS** URL; **no** local Docker required for users |
| Tokens | Per user, per machine | Per user, per machine (not on MCP server) |

**End users** receive **[MDAS-MCP-Client](https://github.com/vt-mdas/MDAS-MCP-CLIENT)** only—not the full server repo—unless they operate MCP themselves.

---

## Using MCP in Cursor (internal quick start)

1. **Operators:** ensure hosted MCP and WebAPI dev are up.
2. **User:** `pip install -r requirements.txt` in **MDAS-MCP-Client**.
3. **Cursor → MCP:** enable **mdas-local** (stdio, paths in `examples/cursor-mcp.json.example`).
4. **Ask:** e.g. *“Get level 1 quotes for AAPL using the level1 tool.”*
5. **Generic equity quotes** use **`level1`**, not Polygon tools, unless the user asks for Polygon.

See [USER-MANUAL.md](USER-MANUAL.md) and [demo-prompts.md](demo-prompts.md).

---

## MCP tools (68 today)

The MCP server exposes **68 tools** today—all backed by existing WebAPI **quote**, **fundamental**, and **reformat** endpoints. After you connect **mdas-local** in Cursor, the full tool list appears in the MCP panel (names and descriptions update with each server release).

| Category | Count | Examples |
|----------|------:|----------|
| **Named shortcuts** | 3 | `level1`, `option_chain_dates`, `company_profile` |
| **Quote tools** | 42 | `quote_*` — equities, options, bonds, FX, international, night session, Polygon, charts, search, snapshots |
| **Fundamental tools** | 8 | `fund_*` — profile, screener filters, ETFs/ETNs, master file, option corporate actions, EOD |
| **Generic escape hatches** | 2 | `quote_endpoint`, `fundamental_endpoint` — any registered quote/fundamental path |
| **Reformat helpers** | 13 | `reformat_*` — same data, common display shapes (equity, option, bonds, FX, search, historical, etc.) |

**Source:** `quote_tools.py` registers 53 tools; `server.py` adds 15 (2 escape hatches + 13 `reformat_*`).

### Roadmap — management API tools (planned)

Today MCP covers **market-data** quote and fundamental APIs only. **We plan to add MCP tools for all WebAPI management APIs**—e.g. user and session administration, firms, entitlements, permissions, integrations, logging, and other operator/admin endpoints—so assistants can perform the same management tasks allowed by a user’s JWT and role, not only market-data lookups. New tools will ship incrementally; this doc will be updated as each area is exposed.

---

## Authentication — next steps (under research)

**Today:** **Approach A** (website login → handoff mint/exchange → loopback **9847** → stdio proxy) is what we ship for **Cursor / desktop** internal use.

**Under research** for broader company and third-party MCP clients:

| Topic | Why it matters |
|-------|----------------|
| **OAuth B** (`/authorize` + `/token` + PKCE) | May let HTTP-native clients (e.g. Cursor without stdio proxy) use standard OAuth instead of custom handoff |
| **Hosted handoff bridge** (no local **9847**) | Needed if clients cannot run a loopback listener—options include pairing/poll, SPA callback + poll, or deeplinks |
| **Multi-client token model** | Who stores refresh tokens, how clients re-auth, agreement/signing in authorize vs mint flows |

**Design constraint (unchanged):** the **MCP HTTP server on AWS stays stateless**—no long-lived user tokens stored on `server.py`; each client/host owns credential storage.

Reference material: `WebAPI-Server/docs/MCP-API-Server-Developer-Guide.md` (Approach A today; Approach B and hosted callback notes for comparison).

---

## Troubleshooting (common)

| Symptom | Likely cause |
|---------|----------------|
| Browser login works but MCP still 401 | Stale tokens—restart MCP in Cursor or delete `%LOCALAPPDATA%\.mdas-mcp\tokens.json` and sign in again |
| **9847** never hit | Website did not run **mint** or redirect to loopback—check DevTools → Network |
| Docker logs show GET `/.well-known` / `/sse` 401/501 | Normal probes when something hits MCP over HTTP without stdio proxy |
| Tool calls **polygon/snapshot** for “quote AAPL” | Ask explicitly for **`level1`**, or use updated tool descriptions (prefer `level1` for generic quotes) |
| Agreements blocking quotes | Complete signing on the website; retry tool |

---

## Related documentation

| Document | Use |
|----------|-----|
| [APPROACH-A-STDIO-PROXY.md](APPROACH-A-STDIO-PROXY.md) | Proxy env vars, smoke test, handoff |
| [DEMO.md](DEMO.md) / [DEMO-CHECKLIST.md](DEMO-CHECKLIST.md) | Demo runbook |
| [../README.md](../../README.md) | Server deploy, distribution to others |
| [MDAS-MCP-Client README](../../../MDAS-MCP-Client/README.md) | End-user kit |
| `WebAPI-Server/docs/MCP-*-Developer-Guide.md` | API, frontend, and MCP host contracts |

---

## Summary

We added **MCP access to MDAS market data** using **existing WebAPI auth**: website login → handoff → local token storage → **stateless MCP on AWS** — **68 quote and fundamental tools today**, with **all WebAPI management APIs planned as MCP tools** next. **Cursor users** run a small **stdio proxy** on their machine; **operators** run **MDAS-MCP** in Docker/AWS. This is the supported internal pattern for **dev** and the basis for rolling out to broader company use.
