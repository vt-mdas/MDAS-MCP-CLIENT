# MDAS-MCP User Manual

This guide is for **people who use MDAS through Cursor**. It explains how to connect, sign in and ask your assistant for market data.

You don't install or run anything locally. Cursor connects directly to the hosted MDAS-MCP server.

---

## 1. What you get

MDAS-MCP lets your AI assistant call MDAS market-data capabilities as **tools**, such as:

- Equity level-1 quotes
- Option chains and option quotes
- Fund / ETF data
- Reformatted quote endpoints

You ask in plain language and the assistant picks the right tool. You never paste an API token into chat; Cursor handles authentication.

---

## 2. What you need

| Item | Notes |
|------|--------|
| **Cursor** | Recent version with remote HTTP MCP support |
| **MDAS account** | The same credentials you use on the MDAS website |
| **MCP server URL** | staging: `https://mdas-mcp-staging.viewtrade.dev/mcp` · dev: `https://mdas-mcp-dev.viewtrade.dev/mcp` |
| **Network** | Access to the MDAS website and the MCP host |

---

## 3. Connect Cursor

### 3.1 Add the server

Add an HTTP MCP server to `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (workspace):

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

For **dev**, set `url` to `https://mdas-mcp-dev.viewtrade.dev/mcp` (and name the server something like `mdas-dev`).

Cursor detects the change automatically. You don't need to restart.

### 3.2 Authenticate

MDAS-MCP tools load only after you sign in.

1. In Cursor's **MCP** settings, the server appears under **Needs Attention** with the status *Needs authentication*. This happens when the server is freshly added or not yet authenticated.
2. Click **Authenticate**.
3. Your browser opens the **MDAS login page**. Sign in with your MDAS username and password.
4. **Entitlement signing (if required):** if you have entitlements to sign, you are redirected to the signing page. Complete it to continue.
5. The browser redirects to the **handoff page**, which sends you back to Cursor. Cursor waits for this callback, so keep it open.
6. On success, the server shows as **Connected** and Cursor loads all MDAS tools.

Never type passwords or tokens into the chat window.

### 3.3 Session expiry

If your session expires during a chat, Cursor re-authenticates in the background and your request continues. You normally don't need to sign in again.

---

## 4. Using MDAS in conversation

Once connected, ask normally. The assistant picks tools for you.

### Example requests

| You might say | Typical data |
|---------------|--------------|
| "Level 1 for AAPL and MSFT" | Equity quotes |
| "Option chain dates for SPY" | Available expiration dates |
| "Option chain for SPY on 2026-06-20" | Chain for one date |
| "Best quote for TSLA" | Best bid/offer snapshot |
| "Search symbols matching apple" | Symbol search |
| "ETF screener filters" | Fund / ETF tools |

### Tool names (optional reference)

You rarely need these yourself; the assistant sees them automatically. Common groups:

- **Quotes:** `level1`, `quote_best_quote`, `quote_option_chain`, `quote_symbol_search`, …
- **Fundamentals:** `fund_etfs`, `fund_option_corporate_actions`, …
- **Reformat API:** `reformat_equity`, `reformat_option`, `reformat_search`, …

---

## 5. When something goes wrong

### Connection and sign-in

| What you see | What to do |
|--------------|------------|
| Server doesn't appear in Cursor | Check `mcp.json` is valid JSON and the `url` ends in `/mcp`; restart Cursor |
| *Needs authentication* with an **Authenticate** button | Click **Authenticate** and complete the browser sign-in |
| Browser doesn't open after clicking **Authenticate** | Toggle the server off and on in the MCP settings, or restart Cursor |
| Browser stuck on the handoff page | Make sure Cursor is still running, then click **Authenticate** again |
| Server returns to *Needs authentication* mid-session | Background re-authentication didn't complete. Click **Authenticate** again |
| Asked to sign entitlements | Complete signing in the browser; the flow continues to the handoff page |

### Data or permission errors

| What you see | What to do |
|--------------|------------|
| "User is suspended" or similar | Contact your MDAS administrator |
| Empty or "not found" results | Check symbol spelling, market and your entitlements on the website |
| Slow responses | Retry; if it persists, note the time and symbol and contact support |

### What not to do

- Don't paste JWTs, refresh tokens or passwords into chat.
- Don't share screenshots of tokens, or of browser URLs that contain `code=` or `state=`.
- Don't look for a `login` tool in MCP. Sign-in always goes through Cursor's **Authenticate** button and the browser.

---

## 6. Privacy and security

- Cursor stores your token securely, much like staying logged in on the website.
- Every request uses your personal entitlements: tools can fetch only what you can see on the website.
- Anyone with access to your unlocked machine could use your active MDAS session in Cursor. Lock your PC when you step away.

---

## 7. Quick checklist

1. Add the MCP URL for your environment (staging or dev) to `mcp.json` as an `http` server.
2. In Cursor's MCP settings, click **Authenticate**.
3. Sign in on the MDAS login page, sign entitlements if asked, and let the handoff page return you to Cursor.
4. Confirm the server shows **Connected** with tools loaded.
5. Ask for data in plain language.

For demo prompts, see [demo-prompts.md](demo-prompts.md). For architecture and roles, see [COMPANY-USAGE.md](COMPANY-USAGE.md).
