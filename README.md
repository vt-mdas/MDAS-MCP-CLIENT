# MDAS-MCP-Client

Minimal kit for **developers and end users** who connect **Cursor**, **Claude Desktop**, or other **stdio MCP** clients to a **hosted** MDAS-MCP service (AWS / dev). You do **not** need `server.py`, Docker, or the full `MDAS-MCP` repo.

**Repository:** [github.com/vt-mdas/MDAS-MCP-CLIENT](https://github.com/vt-mdas/MDAS-MCP-CLIENT)

The hosted MCP server (`POST /mcp`) is operated by your platform team. This folder runs only **`mcp_stdio_proxy.py`** on your machine: auth (API login or browser handoff), token storage, and stdio ↔ HTTP bridging.

## Contents

| File | Purpose |
|------|--------|
| `mcp_stdio_proxy.py` | **Single script** — stdio host, API login / browser handoff, token store, config loader |
| `validate_quote.py` | Optional post-login check (WebAPI level1 probe) |
| `config.example.json` | Template — copy to `config.json` if needed |
| `config.aws.json` | **Default** — dev hosted MCP + WebAPI URLs |
| `requirements.txt` | Python deps for the proxy only |
| `docs/USER-MANUAL.md` | How to ask for data and troubleshoot auth |
| `docs/APPROACH-A-STDIO-PROXY.md` | Env vars, API login, handoff, MCP logs |
| `docs/demo-prompts.md` | Example assistant prompts |
| `examples/cursor-mcp.json.example` | Paste into `.cursor/mcp.json` |
| `run-proxy.ps1` / `run-proxy.bat` | Optional: login / handoff without Cursor |

**Source of truth:** `mcp_stdio_proxy.py` is copied from [`../MDAS-MCP/application/`](../MDAS-MCP/application/). When the proxy changes upstream, re-copy that file (and optionally `validate_quote.py` + docs).

## Quick start

### 1. Install Python dependencies

```bash
cd MDAS-MCP-Client
python -m pip install -r requirements.txt
```

Python **3.12+** recommended.

### 2. Configure environment (usually no edit)

`config.json` and `config.aws.json` both point at **dev** by default (hosted MCP). Edit either file or copy `config.example.json` for other environments.

- MCP: `https://mdas-mcp-dev.viewtrade.dev`
- WebAPI: `https://mdas-api-dev.viewtrade.dev`
- Website login: `https://mdas-app-dev.viewtrade.dev/login?source=mcp`

`validate_quote.py` and `run-proxy.ps1` use `config.json` by default; the Cursor example uses `config.aws.json` (same content).

### 3. Add MCP in Cursor

Copy [`examples/cursor-mcp.json.example`](examples/cursor-mcp.json.example) into your workspace **`.cursor/mcp.json`** (adjust paths and `python` / `python.exe`).

Enable the server in **Cursor Settings → MCP**.

### 4. Sign in once

MCP uses the **same `access_token` as the REST API** (`Authorization: Bearer`). Pick one:

**A — Login API (no browser)**

```powershell
.\run-proxy.ps1 -LoginOnly -Username YOUR_USER -Password YOUR_PASS
# or:
python .\mcp_stdio_proxy.py --login-only --username YOUR_USER --password YOUR_PASS --config .\config.aws.json
```

**B — Existing token from `POST /api/user/login`**

```powershell
$env:MDAS_ACCESS_TOKEN = "<access_token>"
$env:MDAS_REFRESH_TOKEN = "<refresh_token>"   # optional
```

Then start Cursor / the proxy as usual.

**C — Browser handoff (website)**

On first use, the proxy opens your browser → log in on the MDAS website → redirect to `http://127.0.0.1:9847/callback`.

Tokens are saved to: `%LOCALAPPDATA%\.mdas-mcp\tokens.json` (Windows) or `~/.mdas-mcp/tokens.json` (macOS/Linux).  
Username/password env vars are **not** written to disk — only tokens are.

### 5. Verify (optional)

```bash
python validate_quote.py
```

Expect `PASS: level1 probe` and a sample quote.

## Optional: login without Cursor

```powershell
# API login (same as REST)
.\run-proxy.ps1 -LoginOnly -Username YOUR_USER -Password YOUR_PASS

# Browser handoff
.\run-proxy.ps1 -HandoffOnly
```

Then enable MCP in Cursor; it reuses `tokens.json`.

### Cursor `env` for API login (optional)

You can put credentials in `.cursor/mcp.json` `env` (prefer OS secrets / local-only config — do not commit passwords):

```json
"env": {
  "MDAS_MCP_HTTP_URL": "https://mdas-mcp-dev.viewtrade.dev/mcp/",
  "MDAS_USERNAME": "YOUR_USER",
  "MDAS_PASSWORD": "YOUR_PASS"
}
```

Or seed a token:

```json
"env": {
  "MDAS_ACCESS_TOKEN": "<access_token from login>",
  "MDAS_REFRESH_TOKEN": "<refresh_token>"
}
```

## Auth priority

1. `MDAS_ACCESS_TOKEN` (optional `MDAS_REFRESH_TOKEN` / `MDAS_USER_ID`)
2. Stored `tokens.json` (+ refresh)
3. `POST /api/user/login` via `MDAS_USERNAME` / `MDAS_PASSWORD` or `--login-only`
4. Browser handoff (`mdas.website_login_url`)

## What you need from your administrator

| Item | Example (dev) |
|------|----------------|
| MCP HTTP URL | `https://mdas-mcp-dev.viewtrade.dev/mcp/` |
| Website login | `https://mdas-app-dev.viewtrade.dev/login?source=mcp` |
| MDAS account | Same as the website; required entitlements |

## HTTP-native MCP clients

If your tool supports **HTTP MCP** and can send **`Authorization: Bearer {access_token}`** (from login or handoff), you may only need the MCP URL and [`docs/USER-MANUAL.md`](docs/USER-MANUAL.md). **Cursor** should use this client kit (stdio proxy).

## Do not

- Commit or share `tokens.json`, JWTs, or passwords.
- Run two stdio proxies at once (Cursor + Claude Desktop + `run-proxy` handoff) — they share port **9847** and the same token file.
- Enable both a **stdio** server and a duplicate **HTTP** `url` entry in Cursor for the same backend.

## More documentation

| Doc | Topic |
|-----|--------|
| [docs/APPROACH-A-STDIO-PROXY.md](docs/APPROACH-A-STDIO-PROXY.md) | Troubleshooting, env vars, API login, re-login |
| [docs/USER-MANUAL.md](docs/USER-MANUAL.md) | End-user usage and errors |
| [../MDAS-MCP/README.md](../MDAS-MCP/README.md) | Deploying `server.py` (operators only) |
