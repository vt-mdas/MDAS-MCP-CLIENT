# MDAS-MCP demo prompts (Cursor)

Copy these into Cursor **after** the MDAS server shows **Connected** in Cursor's MCP settings (see the [README](../README.md) for setup). Use the symbols your demo account is entitled to see.

**Recommended demo symbols:** `AAPL`, `MSFT`, `SPY` (adjust if your entitlements differ).

> **Before the demo:** don't sign in with the demo account anywhere else (website, another Cursor) during the demo. That revokes the Cursor session.

---

## Act 1 — Equity quotes (happy path)

### Prompt 1

```text
Get level 1 quotes for AAPL and MSFT.
```

| Expected | |
|----------|--|
| Tool | `level1` (or similar) |
| Success | JSON with last price, bid/ask, volume, etc. for both symbols |
| Failure | Server shows *Needs authentication* → session revoked, click **Authenticate**; API 500 / S3Service → fix WebAPI first |

### Prompt 2 (optional)

```text
Show me the best quote snapshot for TSLA.
```

| Expected | |
|----------|--|
| Tool | `quote_best_quote` |
| Success | NBBO / best quote fields |

---

## Act 2 — Options

### Prompt 3

```text
What option chain expiration dates are available for SPY?
```

| Expected | |
|----------|--|
| Tool | `option_chain_dates` or `quote_option_chain_dates` |
| Success | List of dates |

### Prompt 4 (optional, only if you have a valid date from prompt 3)

```text
Show the option chain for SPY on 2026-06-20.
```

Replace the date with one returned in prompt 3.

| Expected | |
|----------|--|
| Tool | `quote_option_chain` or `option_chain` |
| Success | Chain strikes / contracts for that expiry |

---

## Act 3 — Search

### Prompt 5

```text
Search for symbols matching "apple" with a limit of 10.
```

| Expected | |
|----------|--|
| Tool | `quote_symbol_search`, `reformat_search`, or similar |
| Success | Symbol list (may include AAPL and related tickers) |

---

## Act 4 — Fundamentals (optional)

### Prompt 6

```text
List ETF screener filters available in MDAS.
```

| Expected | |
|----------|--|
| Tool | `fund_etfs` or `fund_screener_filters` |
| Success | Filter metadata or ETF list (depends on endpoint) |

---

## What to say if something fails

| Symptom | Likely cause | What to tell the audience |
|---------|----------------|---------------------------|
| Error 500 / S3Service in API logs | API deployment DI bug | “Upstream API issue—we validate API with curl before MCP.” |
| Empty or “not found” | Symbol or entitlement | “This account may not have that market; we’ll try AAPL instead.” |
| MCP server unreachable / no tools | Hosted MCP for that environment is down | “The hosted MCP service is being checked—we’ll switch to the other environment.” |
| Server shows *Needs authentication* mid-demo | Session revoked (demo account signed in elsewhere) or renewal failed | Click **Authenticate**: “MDAS allows one active session per account, so signing in elsewhere ends this one. We sign in on the MDAS website; the assistant never sees your password.” |

---

## Prompts to avoid in a short demo

- Bonds screener, night session, polygon tools (unless pre-tested).
- Large option chains without a date filter.
- `quote_endpoint` escape hatch (too low-level for business audience).

---

## Narration cheat sheet (one line each)

1. **Level 1** — “Real-time equity snapshot from MDAS.”
2. **Option dates** — “Shows which expirations exist before we pull a full chain.”
3. **Search** — “Same symbol search as the website, driven through natural language.”
