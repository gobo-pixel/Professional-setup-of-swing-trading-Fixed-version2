"""
DIAGNOSTIC ONLY — captures RAW yfinance .news behavior.

This is NOT a fix. It exists purely to gather precise, ground-truth
evidence about why MACRO_NEWS_SOURCES tickers (RELIANCE.NS, TCS.NS,
etc.) return empty .news while held-position tickers reliably return
real headlines, in the same script run.

Run this in GitHub Actions and share the FULL output — every line
matters (timestamps, exact types, exact lengths, any exceptions).

Usage:
    python scripts/diagnose_news_fetch.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yfinance as yf  # noqa: E402

print(f"yfinance version: {yf.__version__}")
print(f"Script start time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 70)


def probe(symbol: str, label: str) -> None:
    """Fetch .news for one symbol and print everything about the raw result."""
    t0 = time.time()
    print(f"\n[{time.strftime('%H:%M:%S')}] Probing {symbol} ({label})")
    try:
        ticker = yf.Ticker(symbol)
        news = ticker.news
        elapsed = time.time() - t0
        print(f"  -> type(news) = {type(news)}")
        print(f"  -> news is None: {news is None}")
        if news is not None:
            print(f"  -> len(news) = {len(news)}")
            if len(news) > 0:
                print(f"  -> repr(news[0])[:300] = {repr(news[0])[:300]}")
        print(f"  -> elapsed: {elapsed:.2f}s")
    except Exception as exc:
        elapsed = time.time() - t0
        print(f"  -> EXCEPTION: {type(exc).__name__}: {exc}")
        print(f"  -> elapsed: {elapsed:.2f}s")


# ---- Test 1: query a MACRO-list symbol FIRST, before anything else ----
print("\n### TEST 1: RELIANCE.NS as the very first call ###")
probe("RELIANCE.NS", "macro-list, first-ever call")

# ---- Test 2: query a HELD-POSITION-style symbol next ----
print("\n### TEST 2: A smaller/held-position-style symbol next ###")
probe("HAL.NS", "held-position-style symbol")

# ---- Test 3: query the SAME macro-list symbol AGAIN immediately ----
print("\n### TEST 3: RELIANCE.NS queried AGAIN (repeat, no delay) ###")
probe("RELIANCE.NS", "macro-list, repeat query")

# ---- Test 4: query SUNPHARMA.NS (in BOTH lists) fresh ----
print("\n### TEST 4: SUNPHARMA.NS (overlaps both lists) ###")
probe("SUNPHARMA.NS", "overlap symbol, first call")

# ---- Test 5: wait 5 seconds, then query SUNPHARMA.NS again ----
print("\n### TEST 5: wait 5s, then SUNPHARMA.NS again ###")
time.sleep(5)
probe("SUNPHARMA.NS", "overlap symbol, after 5s wait")

# ---- Test 6: try TCS.NS (another macro-list symbol, fresh) ----
print("\n### TEST 6: TCS.NS fresh ###")
probe("TCS.NS", "macro-list, fresh")

# ---- Test 7: check if get_news() (alternate/newer method) exists and differs ----
print("\n### TEST 7: Does Ticker have an alternate news method? ###")
ticker = yf.Ticker("TCS.NS")
methods = [m for m in dir(ticker) if "news" in m.lower()]
print(f"  -> methods containing 'news': {methods}")
if hasattr(ticker, "get_news"):
    try:
        alt_news = ticker.get_news()
        print(f"  -> get_news() type: {type(alt_news)}, len: {len(alt_news) if alt_news else 'N/A'}")
    except Exception as exc:
        print(f"  -> get_news() EXCEPTION: {type(exc).__name__}: {exc}")

print("\n" + "=" * 70)
print(f"Script end time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
print("=== END DIAGNOSTIC — please share this ENTIRE output ===")

# ---- Test 8: replicate the REAL pipeline's exact call pattern ----
# Real pipeline: 16 "held position" news calls FIRST, then 11
# MACRO_NEWS_SOURCES calls. This isolated test only made 6 calls total
# (all succeeded) — this test replicates the REAL volume/pattern to
# see if cumulative call count within ONE script run is what matters.
print("\n\n" + "#" * 70)
print("### TEST 8: Replicating REAL pipeline's exact 16+11 call pattern ###")
print("#" * 70)

held_position_style = [
    "CHENNPETRO.NS", "HAL.NS", "SUNPHARMA.NS", "IIFL.NS", "MANAPPURAM.NS",
    "INDUSINDBK.NS", "ADANIENSOL.NS", "RKFORGE.NS", "JUBLFOOD.NS", "TATAELXSI.NS",
    "JUBLINGREA.NS", "MFSL.NS", "HEG.NS", "TMPV.NS", "KEC.NS", "SONACOMS.NS",
]
macro_sources = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "MARUTI.NS", "ITC.NS",
    "SUNPHARMA.NS", "LT.NS", "NTPC.NS", "TATASTEEL.NS", "DLF.NS", "BHARTIARTL.NS",
]

print(f"\n[{time.strftime('%H:%M:%S')}] --- Phase A: {len(held_position_style)} 'held position' calls ---")
phase_a_results = []
for sym in held_position_style:
    try:
        n = yf.Ticker(sym).news
        phase_a_results.append((sym, len(n) if n else 0))
    except Exception as exc:
        phase_a_results.append((sym, f"EXCEPTION: {exc}"))
for sym, res in phase_a_results:
    print(f"  {sym}: {res}")

print(f"\n[{time.strftime('%H:%M:%S')}] --- Phase B: {len(macro_sources)} macro-source calls (calls #{len(held_position_style)+1}-{len(held_position_style)+len(macro_sources)} of this run) ---")
phase_b_results = []
for sym in macro_sources:
    try:
        n = yf.Ticker(sym).news
        phase_b_results.append((sym, len(n) if n else 0))
    except Exception as exc:
        phase_b_results.append((sym, f"EXCEPTION: {exc}"))
for sym, res in phase_b_results:
    print(f"  {sym}: {res}")

print(f"\n[{time.strftime('%H:%M:%S')}] === TEST 8 COMPLETE ===")
print("=== please share this section too ===")
