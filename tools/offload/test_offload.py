#!/usr/bin/env python3
"""Self-check for the mechanical quote-gate (no server needed). Run: python test_offload.py"""
import offload
raw = "alpha line one\nbeta max_connections=50 here\ngamma retry_backoff_ms=2000\ndelta end"
src = raw.split("\n")

# real quote, correct line -> verified
assert offload.verify_quote("beta max_connections=50 here", 2, src, raw) is True
# model copied the "N: " prefix -> still verified (prefix stripped)
assert offload.verify_quote("2: beta max_connections=50 here", 2, src, raw) is True
# whitespace differs -> normalized match still verified
assert offload.verify_quote("beta   max_connections=50    here", 2, src, raw) is True
# line number off but quote real -> verified (whole-doc fallback)
assert offload.verify_quote("retry_backoff_ms=2000", 99, src, raw) is True
# FABRICATED quote (not in source) -> NOT verified  <-- the gate's whole point
assert offload.verify_quote("max_connections=9999 unlimited", 2, src, raw) is False
# injection-style claim with empty quote -> NOT verified
assert offload.verify_quote("", 1, src, raw) is False
# partial hallucination (real words, false value) -> NOT verified
assert offload.verify_quote("beta max_connections=500 here", 2, src, raw) is False
print("OK_PASS: quote-gate verifies real quotes and rejects fabricated ones")
