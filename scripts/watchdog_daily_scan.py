"""
WATCHDOG — Alerts if Daily Scan hasn't started within its expected window.

Standalone by design: does NOT import from the main codebase, so it
keeps working even if something else in the app is broken. Uses only
the GitHub REST API (via GITHUB_TOKEN, already available in Actions)
and a direct Telegram API call.

Catches: GitHub Actions hosted-runner queue congestion (or any other
reason Daily Scan didn't start on time) — not a fix for the delay
itself, just visibility so it's noticed immediately instead of
discovered later.

Run this on its own schedule, some minutes AFTER Daily Scan's expected
start time (see the paired workflow file).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import requests

WORKFLOW_FILE = "daily_scan.yml"
EXPECTED_MAX_DELAY_MINUTES = 45


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
    github_token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not github_token or not repo:
        print("GITHUB_TOKEN/GITHUB_REPOSITORY not set — cannot check workflow status.")
        sys.exit(1)

    headers = {"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github+json"}
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{WORKFLOW_FILE}/runs?per_page=5"

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        runs = resp.json().get("workflow_runs", [])
    except Exception as exc:
        send_telegram_alert(f"⚠️ Watchdog could not check Daily Scan status: {exc}")
        sys.exit(1)

    if not runs:
        send_telegram_alert(
            "🔴 WATCHDOG: No Daily Scan runs found at all via GitHub API — "
            "please check manually."
        )
        return

    latest = runs[0]
    created_at = datetime.fromisoformat(latest["created_at"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    age_minutes = (now - created_at).total_seconds() / 60

    print(f"Latest Daily Scan run created at: {created_at.isoformat()} ({age_minutes:.1f} min ago)")
    print(f"Status: {latest.get('status')}, Conclusion: {latest.get('conclusion')}")

    if age_minutes > EXPECTED_MAX_DELAY_MINUTES:
        send_telegram_alert(
            f"🟠 WATCHDOG: Daily Scan hasn't started in the last "
            f"{EXPECTED_MAX_DELAY_MINUTES} minutes (last run was "
            f"{age_minutes:.0f} min ago). Likely a GitHub Actions "
            f"runner-queue delay — no code issue, just flagging for visibility."
        )
    else:
        print("OK — Daily Scan started within the expected window. No alert needed.")


if __name__ == "__main__":
    main()
