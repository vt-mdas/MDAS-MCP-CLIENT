# Approach A — stdio MCP host (`mcp_stdio_proxy.py`)

**MDAS-MCP-Client** folder: run only this proxy on your workstation. The hosted service (AWS / dev) runs **`server.py`** (`POST /mcp`). Cursor and many other MCP clients speak **stdio** reliably.

The **`mcp_stdio_proxy.py`** wrapper lives in the **MDAS-MCP-Client** root (this kit). Cursor spawns it as the MCP server process. That process:

1. Ensures credentials (stored file or interactive handoff).
2. **Opens the browser** to `mdas.website_login_url` (`?source=mcp`).
3. **Listens** on the API-default loopback URI **`http://127.0.0.1:9847/callback`** (`McpHandoff:DefaultRedirectUri` — see [`WebAPI-Server/application/appsettings.json`](../../../WebAPI-Server/application/appsettings.json)).
4. After the SPA **mint** redirects with `code` + `state`, calls **`POST {api_base_url}/api/user/handoff/exchange`** (same payload as Cursor would).
5. Saves **`access_token`**, **`refresh_token`**, **`user_id`** under `%LOCALAPPDATA%\.mdas-mcp\tokens.json` on Windows (or **`~/.mdas-mcp/tokens.json`** on macOS/Linux) unless **`MDAS_TOKEN_PATH`** overrides.
6. **Bridges** MCP JSON-RPC over stdio ↔ Streamable HTTP to **`MDAS_MCP_HTTP_URL`** (defaults to **`{mdas.resource_url}/mcp`** from `config.json`).

**Token storage:** the Docker **`server.py`** process does **not** persist credentials — it reads ``Authorization`` / ``X-MDAS-*`` per request. This proxy owns **`tokens.json`**, validates tokens against WebAPI before bridging, refreshes via ``/api/user/refresh`` when possible, and persists ``X-MDAS-Access-Token`` response headers from MCP.

## Prerequisites

- **Website** redirects after mint to the **same URI** WebAPI mint resolved (typically default `http://127.0.0.1:9847/callback`) — must remain in **`McpHandoff:AllowedRedirectUris`**.
- **Hosted MCP** reachable at `mdas.resource_url` in **`config.aws.json`** (default dev: `https://mdas-mcp-dev.viewtrade.dev`).
- Python **3.12+** with **`requirements.txt`** in this folder installed on your machine (`pip install -r requirements.txt`).

You do **not** run `server.py` or Docker from this kit unless your admin told you to use a local MCP on port 8000 (see `config.example.json` in the full `MDAS-MCP` repo).

## Cursor `mcp.json` (recommended)

Copy [`examples/cursor-mcp.json.example`](../examples/cursor-mcp.json.example) to your workspace **`.cursor/mcp.json`**, enable **`mdas`** under **Cursor Settings → MCP**.

```json
{
  "mcpServers": {
    "mdas": {
      "command": "python",
      "args": [
        "${workspaceFolder}/MDAS-MCP-Client/mcp_stdio_proxy.py",
        "--config",
        "${workspaceFolder}/MDAS-MCP-Client/config.aws.json"
      ],
      "cwd": "${workspaceFolder}/MDAS-MCP-Client",
      "env": {
        "MDAS_MCP_HTTP_URL": "https://mdas-mcp-dev.viewtrade.dev/mcp/"
      }
    }
  }
}
```

On Windows use the **full path** to `python.exe` under `command` if `python` is the Store stub.

**Do not** add a duplicate HTTP `url` MCP entry for the same hosted `/mcp` while using stdio — it adds noise without helping Cursor.

Login still uses loopback **`127.0.0.1:9847/callback`**; quote tools hit the hosted MCP.

**Cursor shows “no tools”:** open **MCP → mdas → Show logs**. Common causes: (1) proxy waiting for browser login; (2) `python` not on PATH; (3) proxy import error — run `pip install -r requirements.txt`; (4) AWS ALB needs **stickiness** for Streamable HTTP. After login, you should see dozens of quote tools.

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

Optional connectivity check against a running MCP host (operators / advanced):

```powershell
cd MDAS-MCP-Client
$env:MDAS_SMOKE_MCP_BASE = "https://mdas-mcp-dev.viewtrade.dev"
python .\mcp_stdio_proxy.py --smoke --config .\config.aws.json
```

This checks **`/health`**, **`.well-known`**, **`/mcp` (401)**, **`/sse` (501)**, and **`POST …/handoff/exchange`** with a dummy code (expects **401**, not connectivity failure). Local Docker smoke tests live in the full **`MDAS-MCP`** repo.

## One-shot handoff (no Cursor)

Smoke-test exchange + disk storage:

```powershell
cd MDAS-MCP-Client
.\run-proxy.ps1 -HandoffOnly
```

Then start Cursor connecting via stdio; it will reuse **`tokens.json`**.

## One login for end users (normal flow)

1. Enable **`mdas`** in Cursor (stdio proxy) — **do not** also run `python mcp_stdio_proxy.py` in a terminal unless debugging.
2. First tool call (or first proxy start) opens the browser **once**; complete login + mint redirect.
3. Later tool calls reuse **`tokens.json`** (reload on disk change + refresh). **No second browser** if you logged in within the grace window or another process just finished handoff.

**User-visible status:** the proxy prints lines prefixed with **`MDAS Login:`** on stderr (visible in Cursor’s MCP output). While waiting for an in-flight sign-in, it prints periodic “still waiting…” messages. The browser success page says when you can close the tab.

**Cursor MCP log UI:** anything on stderr may appear as `[error]` even when it is only `INFO`. Routine `httpx` request logs are turned off by default; look for **`MDAS Login:`** for real user messages. Use `MDAS_PROXY_LOGLEVEL=INFO` only when debugging the proxy itself.

Avoid: `--handoff-only` immediately followed by a manual proxy start — the second process used to open login again; the proxy now **waits for peer handoff** when `tokens.json` is fresh.

**Re-login without restarting the proxy:** leave **mdas** enabled; run browser login (`run-proxy.ps1 -HandoffOnly` or MCP-driven handoff). The stdio bridge re-reads **`tokens.json` on every HTTP call** to the hosted MCP. Do **not** `taskkill` the proxy. After updating proxy files, toggle **mdas** off/on **once** so Cursor spawns a new child (Python does not hot-reload).

## Troubleshooting

| Symptom | Check |
|---------|-------|
| **`mdas` → Not connected** in Cursor | Cursor only runs the proxy while the server is **enabled**. **Do not** `taskkill` the proxy from a terminal — toggle **off/on** once to reconnect. After **`run-proxy.ps1 -HandoffOnly`**, leave **mdas** on and use a tool call (tokens reload from disk). Ensure hosted MCP is up (`curl https://mdas-mcp-dev.viewtrade.dev/health` or your environment URL). |
| **Port 9847 in use** (`Address already in use`) | Something else listens on **`9847`** (Cursor OAuth also uses common loopback URIs — close conflict or temporarily change **`MDAS_HANDOFF_REDIRECT_URI`** + SPA mint `redirect_uri` + **`McpHandoff:AllowedRedirectUris`**). |
| Redirect never completes | SPA must mint with redirect matching **`MDAS_HANDOFF_REDIRECT_URI`**. Inspect WebAPI **`DefaultRedirectUri`**. |
| **401 / session** after reconnect | Tokens expired — proxy may auto-open login when **`/api/user/refresh`** fails (see **`mdas_trigger_browser_handoff`**); or set **`MDAS_FORCE_HANDOFF=1`** / delete **`tokens.json`**. **`MDAS_NO_AUTO_BROWSER_HANDOFF=1`** turns off automatic browser reopen. After **`--handoff-only`**, a running bridge reloads **`tokens.json`** automatically on the next tool call (no MCP toggle required). |
| **`Exchange` fails** | `code/state` TTL (default 120s), wrong API base, Redis/session missing on WebAPI |

## Related docs

| Doc | Audience |
|-----|----------|
| [MCP-Server-Developer-Guide.md](../../../WebAPI-Server/docs/MCP-Server-Developer-Guide.md) | MCP host checklist |
| [DEMO.md](DEMO.md) | Docker + demo |
