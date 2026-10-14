# MDAS-MCP-Client

How to connect **Cursor** to the hosted **MDAS-MCP** service. You don't install or run anything locally. Cursor connects to the MCP server over HTTPS and handles sign-in with your MDAS credentials.

**Repository:** [github.com/vt-mdas/MDAS-MCP-CLIENT](https://github.com/vt-mdas/MDAS-MCP-CLIENT)

## Environments

| Environment | MCP URL |
|-------------|---------|
| **staging** | `https://mdas-mcp-staging.viewtrade.dev/mcp` |
| **dev** | `https://mdas-mcp-dev.viewtrade.dev/mcp` |

## Setup in Cursor

### 1. Add the MCP config

Add this to **`~/.cursor/mcp.json`** (global; on Windows `%USERPROFILE%\.cursor\mcp.json`) or **`.cursor/mcp.json`** (workspace). A copy is in [`examples/cursor-mcp.json.example`](examples/cursor-mcp.json.example).

```json
{
  "mcpServers": {
    "mdas-staging": {
      "type": "http",
      "url": "https://mdas-mcp-staging.viewtrade.dev/mcp"
    }
  }
}
```

For **dev**, use `https://mdas-mcp-dev.viewtrade.dev/mcp` as the `url` (and name the server something like `mdas-dev`).

### 2. Authenticate

1. Cursor detects the new server automatically. Open Cursor's **MCP** settings.
2. A new or unauthenticated server appears under **Needs Attention** with the status *Needs authentication*. Click **Authenticate**.
3. Your browser opens the **MDAS login page**. Sign in with your MDAS credentials.
4. If you have entitlements to sign, you are redirected to the **entitlement signing page**. Complete it to continue.
5. After login (and entitlement signing if needed), the browser returns you to Cursor. Keep Cursor open until that finishes.
6. On success, the server moves to **Connected** and Cursor loads all MDAS tools. You can now use them in chat.

### 3. Use it

Ask in chat, for example: *"Get level 1 quotes for AAPL and MSFT."* See [`docs/demo-prompts.md`](docs/demo-prompts.md) for more.

### Session expiry

| Case | What happens |
|------|--------------|
| Access token expires; session still valid | Cursor renews it in the background. No re-login needed. |
| Session revoked (for example, you signed in elsewhere) or renewal fails | The server shows *Needs authentication* again. Click **Authenticate** and sign in. |

## Troubleshooting

| Symptom | What to do |
|---------|------------|
| Server doesn't appear in Cursor | Check that `mcp.json` is valid JSON and the `url` ends in `/mcp`; restart Cursor |
| **405 Method Not Allowed** | The URL must end in `/mcp`, not the bare host (for example `https://mdas-mcp-staging.viewtrade.dev/mcp`) |
| No **Authenticate** button / browser doesn't open | Toggle the server off and on in Cursor's **MCP** settings, or restart Cursor |
| Browser doesn't return to Cursor, or Cursor doesn't connect | Make sure Cursor is still open, then click **Authenticate** again |
| Worked, then auth or tools fail / *Needs authentication* again | Session revoked (for example, you signed in elsewhere) or renewal failed. Click **Authenticate** and complete the browser sign-in |
| Connected but empty tools | The environment URL doesn't match the credentials you used, or toggle the server off and on in Cursor's **MCP** settings |
| Duplicate tools | The same environment is configured twice (for example, in both global and workspace `mcp.json`) |

## Don't

- Paste tokens, JWTs or passwords into chat, or commit them to a repo.
- Share screenshots of browser URLs that contain `code=` or `state=` parameters.

## More documentation

| Doc | Topic |
|-----|-------|
| [docs/USER-MANUAL.md](docs/USER-MANUAL.md) | End-user setup, sign-in and errors |
| [docs/COMPANY-USAGE.md](docs/COMPANY-USAGE.md) | Architecture, roles and tool catalog |
| [docs/demo-prompts.md](docs/demo-prompts.md) | Example prompts |
