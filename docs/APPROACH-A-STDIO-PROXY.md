# Approach A — stdio MCP host (`mcp_stdio_proxy.py`)

Docker / ECS still runs **`server.py`** (Streamable HTTP, Bearer-required `/mcp`). Cursor and many other MCP clients speak **stdio** reliably; GitHub/OpenAI MCP HTTP + OAuth probes do **not** run Approach A without extra work.

The **`mcp_stdio_proxy.py`** wrapper lives next to **`server.py`**. Cursor spawns it as the MCP server process. That process:

1. Ensures credentials (stored file or interactive handoff).
2. **Opens the browser** to `mdas.website_login_url` (`?source=mcp`).
3. **Listens** on the API-default loopback URI **`http://127.0.0.1:9847/callback`** (`McpHandoff:DefaultRedirectUri` — see [`WebAPI-Server/application/appsettings.json`](../../../WebAPI-Server/application/appsettings.json)).
4. After the SPA **mint** redirects with `code` + `state`, calls **`POST {api_base_url}/api/user/handoff/exchange`** (same payload as Cursor would).
5. Saves **`access_token`**, **`refresh_token`**, **`user_id`** under `%LOCALAPPDATA%\.mdas-mcp\tokens.json` on Windows (or **`~/.mdas-mcp/tokens.json`** on macOS/Linux) unless **`MDAS_TOKEN_PATH`** overrides.
6. **Bridges** MCP JSON-RPC over stdio ↔ Streamable HTTP to **`MDAS_MCP_HTTP_URL`** (defaults to **`{mdas.resource_url}/mcp`** from `config.json`).

**Token storage:** the Docker **`server.py`** process does **not** persist credentials — it reads ``Authorization`` / ``X-MDAS-*`` per request. This proxy owns **`tokens.json`**, validates tokens against WebAPI before bridging, refreshes via ``/api/user/refresh`` when possible, and persists ``X-MDAS-Access-Token`` response headers from MCP.

## Prerequisites

- **Website** redirects after mint to the **same URI** WebAPI mint resolved (typically default `http://127.0.0.1:9847/callback`) — must remain in **`McpHandoff:AllowedRedirectUris`**.
- **`docker compose up`** (or `python server.py`) reachable at `mdas.resource_url` (e.g. `http://localhost:8000`).
- Python **3.12** with repo **`requirements.txt`** installed on the **workstation**, not inside Docker.

## Cursor `mcp.json` (recommended)

This repo includes **`.cursor/mcp.json`** (workspace MCP config). Open this folder as your Cursor workspace, then enable **`mdas-local`** under **Cursor Settings → MCP** (or MCP panel). Cursor will spawn **`python mcp_stdio_proxy.py --config …/config.json`** for you — no manual `run-proxy` needed for normal coding.

Prefer **stdio** pointing at `mcp_stdio_proxy.py` plus **`--config`** (or `MDAS_CONFIG_PATH`). Equivalent snippets:

```json
{
  "mcpServers": {
    "mdas-local": {
      "command": "python",
      "args": [
        "${workspaceFolder}/MDAS-MCP/application/mcp_stdio_proxy.py",
        "--config",
        "${workspaceFolder}/MDAS-MCP/application/config.json"
      ]
    }
  }
}
```

```json
{
  "mcpServers": {
    "mdas-local": {
      "command": "python",
      "args": [
        "${workspaceFolder}/MDAS-MCP/application/mcp_stdio_proxy.py"
      ],
      "env": {
        "MDAS_CONFIG_PATH": "${workspaceFolder}/MDAS-MCP/application/config.json"
      }
    }
  }
}
```

Adjust path if `MDAS-MCP/` is not repo-root-relative. On Windows ensure `python` is on PATH (use the full interpreter path under `command` if needed).

**Do not** add a duplicate `url`-style server for **`http://localhost:8000/mcp`** in Cursor if you already use **`mdas-local`** stdio — that causes extra OAuth probing in Docker logs without helping the bridge.

### AWS MCP only (no local `server.py`)

Use **one** Cursor server (e.g. **`mdas-dev`** in `.cursor/mcp.json`) with **`config.aws.json`** and **`MDAS_MCP_HTTP_URL=https://mdas-mcp-dev.viewtrade.dev/mcp/`**. Stop local Docker / `python server.py` on port **8000**. Login still uses loopback **`127.0.0.1:9847/callback`**; quote tools hit the hosted MCP. Do not enable **`mdas-local`** and **`mdas-dev`** at the same time.

**Cursor shows “no tools” for `mdas-dev`:** open **MCP → mdas-dev → Show logs**. Common causes: (1) proxy still waiting for browser login (`ensure_tokens` runs before stdio — finish sign-in if a tab opened); (2) `python` not on PATH — set full path to `python.exe` under `command`; (3) proxy crashed (import error — check logs); (4) AWS ALB needs **stickiness** for Streamable HTTP if multiple ECS tasks. After login, you should see dozens of quote tools.

## Environment overrides

| Variable | Purpose |
|----------|---------|
| `MDAS_MCP_HTTP_URL` | Override MCP HTTP base (default `{resource_url}/mcp`). |
| `MDAS_HANDOFF_REDIRECT_URI` | Callback base (must be **127.0.0.1** or **localhost** and allowlisted); default **`http://127.0.0.1:9847/callback`**. |
| `MDAS_TOKEN_PATH` | File path for token JSON (`0600` on Unix best-effort). |
| `MDAS_FORCE_HANDOFF` | Set `1` to ignore stored tokens and run browser login again. |
| `MDAS_NO_AUTO_BROWSER_HANDOFF` | Set `1` to **disable** opening the browser automatically when MCP returns **`mdas_trigger_browser_handoff`** (after **`/api/user/refresh`** failed). Default: auto-handoff on. |
| `MDAS_DISABLE_TOKEN_DISK_RELOAD` | Set `1` to **disable** reloading `tokens.json` when the file changes on disk (default: **on** — each MCP HTTP request checks mtime so `--handoff-only` updates apply without toggling MCP). |
| `MDAS_HANDOFF_GRACE_SECONDS` | If `tokens.json` was written within this many seconds (default **120**), a starting proxy **waits for the in-flight handoff** instead of opening the browser again. |
| `MDAS_PROXY_LOGLEVEL` | Proxy log level on stderr (`WARNING` default). Set `INFO`/`DEBUG` only when troubleshooting. `httpx` HTTP traces are suppressed so Cursor does not mark every `POST /mcp` as `[error]`. |
| `MDAS_SMOKE_MCP_BASE` | **For `--smoke` only:** MCP base when the script runs in Docker (e.g. `http://host.docker.internal:8000`). |

## Automated smoke (no browser)

### From the host (venv / global Python)

Requires **`pip install -r requirements.txt`** next to `mcp_stdio_proxy.py`:

```powershell
cd MDAS-MCP\application
docker compose up -d --build
python .\mcp_stdio_proxy.py --smoke --config .\config.json
```

### From a one-off Docker container (works if host Python has no deps)

Use **`MDAS_SMOKE_MCP_BASE`** so the container reaches MCP on the host (`host.docker.internal` on Docker Desktop for Windows):

```powershell
cd MDAS-MCP\application
docker compose up -d --build
docker run --rm `
  -e MDAS_SMOKE_MCP_BASE=http://host.docker.internal:8000 `
  -v "${PWD}:/work" -w /work python:3.12-slim-bookworm `
  sh -c "pip install --no-cache-dir -q -r requirements.txt && python mcp_stdio_proxy.py --smoke --config /work/config.json"
```

This checks **`/health`**, **`.well-known`**, **`/mcp` (401)**, **`/sse` (501)**, and **`POST …/handoff/exchange`** with a dummy code (expects **401**, not connectivity failure).

## One-shot handoff (no Cursor)

Smoke-test exchange + disk storage:

```powershell
cd MDAS-MCP\application
$env:MDAS_CONFIG_PATH = (Resolve-Path .\config.json)
python .\mcp_stdio_proxy.py --handoff-only --timeout 300
```

Then start Cursor connecting via stdio; it will reuse **`tokens.json`**.

## API login (same `access_token` as REST)

MCP already accepts **`Authorization: Bearer {access_token}`** — identical to quote APIs. You can skip the browser handoff and obtain tokens the same way as any API client:

```powershell
cd MDAS-MCP\application
python .\mcp_stdio_proxy.py --login-only --username YOUR_USER --password YOUR_PASS --config .\config.json
```

Or seed tokens from an existing login response:

```powershell
$env:MDAS_ACCESS_TOKEN = "<access_token from POST /api/user/login>"
$env:MDAS_REFRESH_TOKEN = "<refresh_token>"   # optional, for auto-refresh
$env:MDAS_USER_ID = "<user id>"               # optional if JWT has nameidentifier
# Then start Cursor / the stdio proxy as usual
```

Env vars for non-interactive API login (proxy will call login when tokens are missing):

| Variable | Purpose |
|----------|---------|
| `MDAS_USERNAME` / `MDAS_PASSWORD` | `POST /api/user/login` |
| `MDAS_FORCE_LOGIN=1` | Ignore stored tokens and login again |
| `MDAS_ACCESS_TOKEN` | Use this Bearer directly (same as REST) |

## One login for end users (normal flow)

1. Enable **`mdas-local`** in Cursor (stdio proxy) — **do not** also run `python mcp_stdio_proxy.py` in a terminal unless debugging.
2. First tool call (or first proxy start) opens the browser **once**; complete login + mint redirect.
3. Later tool calls reuse **`tokens.json`** (reload on disk change + refresh). **No second browser** if you logged in within the grace window or another process just finished handoff.

**User-visible status:** the proxy prints lines prefixed with **`MDAS Login:`** on stderr (visible in Cursor’s MCP output). While waiting for an in-flight sign-in, it prints periodic “still waiting…” messages. The browser success page says when you can close the tab.

**Cursor MCP log UI:** anything on stderr may appear as `[error]` even when it is only `INFO`. Routine `httpx` request logs are turned off by default; look for **`MDAS Login:`** for real user messages. Use `MDAS_PROXY_LOGLEVEL=INFO` only when debugging the proxy itself.

Avoid: `--handoff-only` immediately followed by a manual proxy start — the second process used to open login again; the proxy now **waits for peer handoff** when `tokens.json` is fresh.

**Re-login without restarting the proxy:** leave **mdas-local** enabled; run browser login (`--handoff-only` or MCP-driven handoff). The stdio bridge re-reads **`tokens.json` on every HTTP call** to `server.py`. Do **not** `taskkill` the proxy. After pulling proxy code changes, toggle **mdas-local** off/on **once** so Cursor spawns a child running the new script (Python does not hot-reload).

## Troubleshooting

| Symptom | Check |
|---------|-------|
| **`mdas-local` → Not connected** in Cursor | Cursor only runs the proxy while the server is **enabled**. **Do not** `taskkill` the proxy from a terminal — that disconnects MCP until you toggle **off/on** once. After login via **`--handoff-only`**, leave **`mdas-local` on** and use a tool call (tokens reload from disk); if the UI still says Not connected, toggle **once** to spawn a new child. Ensure **`server.py`** is listening on port **8000**. |
| **Port 9847 in use** (`Address already in use`) | Something else listens on **`9847`** (Cursor OAuth also uses common loopback URIs — close conflict or temporarily change **`MDAS_HANDOFF_REDIRECT_URI`** + SPA mint `redirect_uri` + **`McpHandoff:AllowedRedirectUris`**). |
| Redirect never completes | SPA must mint with redirect matching **`MDAS_HANDOFF_REDIRECT_URI`**. Inspect WebAPI **`DefaultRedirectUri`**. |
| **401 / session** after reconnect | Tokens expired — proxy may auto-open login when **`/api/user/refresh`** fails (see **`mdas_trigger_browser_handoff`**); or set **`MDAS_FORCE_HANDOFF=1`** / delete **`tokens.json`**. **`MDAS_NO_AUTO_BROWSER_HANDOFF=1`** turns off automatic browser reopen. After **`--handoff-only`**, a running bridge reloads **`tokens.json`** automatically on the next tool call (no MCP toggle required). |
| **`Exchange` fails** | `code/state` TTL (default 120s), wrong API base, Redis/session missing on WebAPI |

## Related docs

| Doc | Audience |
|-----|----------|
| [MCP-Server-Developer-Guide.md](../../../WebAPI-Server/docs/MCP-Server-Developer-Guide.md) | MCP host checklist |
| [DEMO.md](DEMO.md) | Docker + demo |
