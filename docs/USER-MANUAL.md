# MDAS-MCP User Manual

This guide is for **people who use MDAS through an MCP client** (for example Cursor). It explains how to connect, sign in, and ask your assistant for market data.

You do **not** need to install or run the MCP server yourself. Your team provides the **MCP server URL** (for example a hosted `https://…/mcp` address).

---

## 1. What you get

MDAS-MCP lets your AI assistant call MDAS market-data capabilities as **tools**, such as:

- Equity level-1 quotes
- Option chains and option quotes
- Fund / ETF data
- Reformatted quote endpoints

You talk to the assistant in natural language; it chooses the right tool. There is **no** “paste your API token into the chat” step—your MCP app handles authentication securely.

---

## 2. What you need

| Item | Notes |
|------|--------|
| **MCP client** | Cursor or another app that supports HTTP MCP with sign-in / Bearer tokens |
| **MDAS account** | Same credentials you use on the MDAS website |
| **MCP server URL** | From your administrator (dev example: `https://mdas-mcp-dev.viewtrade.dev/mcp`) |
| **Network** | Access to the MDAS website and MCP host URLs your org uses |

---

## 3. Connect your MCP client

### 3.1 Add the server

Your admin will give you a URL ending in `/mcp`. In Cursor, add an HTTP MCP server pointing at that URL.

Example (your URL will differ):

```json
{
  "mcpServers": {
    "mdas": {
      "type": "http",
      "url": "https://mdas-mcp-dev.viewtrade.dev/mcp"
    }
  }
}
```

The exact settings screen depends on your Cursor version; follow your org’s internal setup doc if one exists.

### 3.2 Sign in (first time)

MDAS-MCP does **not** work without signing in. When you connect or use a tool, your MCP client should:

1. **Open your browser** to the MDAS website login page (with `?source=mcp` so the site knows you came from MCP).
2. **Log in** with your normal MDAS username and password.
3. Complete any **agreement signing** on the website if prompted.
4. Finish the short **handoff** step (browser may redirect briefly; your MCP app completes this in the background).
5. Return to Cursor—you can now use MDAS tools.

You should **not** type passwords or long-lived tokens into the chat window.

When your access token expires, a properly configured MCP client refreshes it automatically in the background (same as the website). You only need to sign in again if refresh fails or your session was revoked.

### 3.3 Agreement signing

If MDAS requires updated agreements, the website will ask you to sign. Do that in the **browser**, then try your request again in the assistant. Signing is always done on the MDAS website, not inside the MCP tool list.

---

## 4. Using MDAS in conversation

Once connected and signed in, ask normally. The assistant picks tools for you.

### Example requests

| You might say | Typical data |
|---------------|--------------|
| “Level 1 for AAPL and MSFT” | Equity quotes |
| “Option chain dates for SPY” | Available expiration dates |
| “Option chain for SPY on 2026-06-20” | Chain for one date |
| “Best quote for TSLA” | Best bid/offer snapshot |
| “Search symbols matching apple” | Symbol search |
| “ETF screener filters” | Fund / ETF tools |

### Tool names (optional reference)

You rarely need these names yourself; the assistant sees them automatically. Common groups:

- **Quotes:** `level1`, `quote_best_quote`, `quote_option_chain`, `quote_symbol_search`, …
- **Fundamentals:** `fund_etfs`, `fund_option_corporate_actions`, …
- **Reformat API:** `reformat_equity`, `reformat_option`, `reformat_search`, …

---

## 5. When something goes wrong

### “Not connected” or authentication errors

| What you see | What to do |
|--------------|------------|
| Prompt to **sign in** or **open browser** | Follow the link; log in on the MDAS website; return to Cursor |
| **401** or “authentication required” | Sign in again through your MCP client’s MDAS connection flow |
| Message about **session expired** or **re-login** | Same as above—your session ended; sign in again |
| **Sign agreement** or signing URL in the response | Open the link in your browser, complete signing, retry your question |
| Tools worked before, now fail after idle time | Sign in again; tokens expire like a normal website session |

### Data or permission errors

| What you see | What to do |
|--------------|------------|
| “User is suspended” or similar | Contact your MDAS administrator |
| Empty or “not found” results | Check symbol spelling, market, and entitlements on the website |
| Slow responses | Retry; if it persists, note the time and symbol and contact support |

### What not to do

- Do **not** paste JWTs, refresh tokens, or passwords into chat.
- Do **not** share screenshots of tokens or login URLs with codes in them.
- Do **not** expect a `login` tool inside MCP—you always use the **website + browser** flow your MCP client provides.

---

## 6. Privacy and security (for users)

- Your MCP client stores the access token securely (same idea as staying logged in on the website).
- Each request to MDAS uses your personal entitlements—what you can see on the website is what tools can fetch.
- If you leave your machine unlocked, someone with access to Cursor could use your active MDAS session; lock your PC when away.

---

## 7. Quick checklist

1. Obtain the **MCP URL** from your administrator.
2. Add it in **Cursor** (or your MCP client).
3. **Sign in** when prompted (browser → MDAS website → return to client).
4. Ask for data in plain language.
5. If auth fails, **sign in again** or complete **agreements** on the website.

For **running or deploying** the MCP server (Docker, AWS, config file), see `README.md` at the repo root (`MDAS-MCP/README.md`)—that is for operators and developers, not end users.

For a **live demo with Cursor**, presenters use [DEMO.md](DEMO.md), [DEMO-CHECKLIST.md](DEMO-CHECKLIST.md), and [demo-prompts.md](demo-prompts.md).

For internal auth/API details, your platform team may reference `MCP-Server-Developer-Guide.md` in the WebAPI repository.
