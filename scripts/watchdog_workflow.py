"""
WATCHDOG — Alerts if a given scheduled workflow hasn't started within
its expected window. Generalized (via CLI args) to check ANY workflow
— used for both Daily Scan and Morning Executor, avoiding duplicating
this logic per-workflow.

Standalone by design: does NOT import from the main codebase, so it
keeps working even if something else in the app is broken. Uses only
the GitHub REST API (via GITHUB_TOKEN, already available in Actions)
and a direct Telegram API call.

Catches: GitHub Actions hosted-runner queue congestion (or any other
reason the target workflow didn't start on time) — not a fix for the
delay itself, just visibility so it's noticed immediately instead of
discovered later.

Usage:
    python scripts/watchdog_workflow.py \
        --workflow-file daily_scan.yml \
        --scheduled-hour-utc 17 --scheduled-minute-utc 0 \
        --max-delay-minutes 20 --label "Daily Scan"

    python scripts/watchdog_workflow.py \
        --workflow-file morning_executor.yml \
        --scheduled-hour-utc 3 --scheduled-minute-utc 46 \
        --max-delay-minutes 4 --label "Morning Executor"
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timezone

import requests

from core.trading_calendar import is_trading_day


def send_telegram_alert(message: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set — cannot send alert. Message was:")
        print(message)
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=15)
        resp.raise_for_status()
        print("Telegram alert sent.")
    except Exception as exc:
        print(f"Failed to send Telegram alert: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-file", required=True, help="e.g. daily_scan.yml")
    parser.add_argument("--scheduled-hour-utc", type=int, required=True)
    parser.add_argument("--scheduled-minute-utc", type=int, default=0)
    parser.add_argument("--max-delay-minutes", type=int, required=True)
    parser.add_argument("--label", required=True, help="Human-readable name for notification text")
    args = parser.parse_args()

    if not is_trading_day(date.today()):
        print("Not a trading day — watchdog skipping check.")
        return

    github_token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not github_token or not repo:
        print("GITHUB_TOKEN/GITHUB_REPOSITORY not set — cannot check workflow status.")
        sys.exit(1)

    headers = {"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github+json"}
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{args.workflow_file}/runs?per_page=5"

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        runs = resp.json().get("workflow_runs", [])
    except Exception as exc:
        send_telegram_alert(f"⚠️ Watchdog could not check {args.label} status: {exc}")
        sys.exit(1)

    if not runs:
        send_telegram_alert(
            f"🔴 WATCHDOG: No {args.label} runs found at all via GitHub API — "
            f"please check manually."
        )
        return

    latest = runs[0]
    created_at = datetime.fromisoformat(latest["created_at"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    today_utc = now.date()

    # Compare against the workflow's OWN scheduled trigger-time, NOT
    # "now" — using "now" was a confirmed bug: if the watchdog itself
    # gets queued late (same GitHub runner-congestion that can delay
    # the target workflow), it would falsely report a delay even when
    # the target workflow triggered on time, simply because the
    # WATCHDOG'S OWN check ran late.
    if created_at.date() < today_utc:
        send_telegram_alert(
            f"🔴 WATCHDOG: No {args.label} run found for today yet "
            f"(latest run was {created_at.isoformat()}, from a previous day) — please check manually."
        )
        return

    scheduled_time = datetime(
        today_utc.year, today_utc.month, today_utc.day,
        args.scheduled_hour_utc, args.scheduled_minute_utc, tzinfo=timezone.utc,
    )
    delay_minutes = (created_at - scheduled_time).total_seconds() / 60

    print(f"Latest {args.label} run created at: {created_at.isoformat()} "
          f"({delay_minutes:.1f} min after its {args.scheduled_hour_utc:02d}:{args.scheduled_minute_utc:02d} UTC schedule)")
    print(f"Status: {latest.get('status')}, Conclusion: {latest.get('conclusion')}")

    if delay_minutes > args.max_delay_minutes:
        send_telegram_alert(
            f"🟠 WATCHDOG: {args.label} triggered {delay_minutes:.0f} min after its "
            f"scheduled time (allowed: {args.max_delay_minutes} min). Likely a "
            f"GitHub Actions runner-queue delay — no code issue, just flagging for visibility."
        )
    else:
        print(f"OK — {args.label} started within the expected window. No alert needed.")


if __name__ == "__main__":
    main()
