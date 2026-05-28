#!/usr/bin/env python3
"""Quick post-login check: probe + AAPL level1 via WebAPI (not MCP)."""
from __future__ import annotations

import json
import sys

import httpx

from mcp_stdio_proxy import (
    load_config,
    TokenStore,
    default_token_file,
    fetch_level1_sample,
    probe_access_token,
)


def main() -> int:
    cfg = load_config()
    store = TokenStore(default_token_file())
    store.reload_disk_state()
    print(f"token file: {store.path}")
    print(f"user_id: {store.user_id}")
    if not store.access:
        print("FAIL: no access_token")
        return 1
    if not probe_access_token(cfg, store.access):
        print("FAIL: level1 probe")
        return 1
    print("PASS: level1 probe")
    sample = fetch_level1_sample(cfg, store.access or "", "AAPL")
    if not sample:
        print("FAIL: could not fetch AAPL level1 sample")
        return 1
    print("AAPL sample:", json.dumps(sample, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
