"""CLI and the daytime loop: check, diff against the last snapshot, alert on anything new."""

from __future__ import annotations

import argparse
import logging
import os
import random
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from watcher import notify, state
from watcher.vhs import SEARCH_URL, Course, VhsClient, einbuergerung_only

log = logging.getLogger("watcher")

TZ = ZoneInfo("Europe/Berlin")
# Re-alert on an ongoing failure streak every N failed checks (~3 h at 30-min gaps).
REMIND_EVERY = 6
# A crash-restart loop would otherwise alert on every container restart.
CRASH_ALERT_MIN_GAP_S = 3600
TOPIC = "Sprachtest zur Einbürgerung"


@dataclass(frozen=True)
class Schedule:
    start_hour: int
    end_hour: int
    min_gap: int
    max_gap: int

    def in_window(self, t: datetime) -> bool:
        return self.start_hour <= t.hour < self.end_hour

    def next_window_start(self, now: datetime, rng: random.Random) -> datetime:
        start = now.replace(hour=self.start_hour, minute=0, second=0, microsecond=0)
        if now >= start:
            start += timedelta(days=1)
        return start + timedelta(minutes=rng.uniform(0, 20))

    def next_run(self, now: datetime, rng: random.Random) -> datetime:
        candidate = now + timedelta(minutes=rng.uniform(self.min_gap, self.max_gap))
        if self.in_window(candidate) and candidate.date() == now.date():
            return candidate
        return self.next_window_start(now, rng)


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "" or value.startswith("REPLACE_"):
        sys.exit(f"{name} is not set (see watcher.env.template)")
    return value


def telegram_config() -> notify.TelegramConfig:
    data_dir = Path(os.environ.get("DATA_DIR", "/data"))
    return notify.TelegramConfig(
        api_id=int(_env("TELEGRAM_API_ID")),
        api_hash=_env("TELEGRAM_API_HASH"),
        chat=os.environ.get("TELEGRAM_CHAT", ""),
        session_path=data_dir / "watcher.session",
    )


def schedule_from_env() -> Schedule:
    return Schedule(
        start_hour=int(os.environ.get("WINDOW_START_HOUR", "7")),
        end_hour=int(os.environ.get("WINDOW_END_HOUR", "20")),
        min_gap=int(os.environ.get("INTERVAL_MIN_MINUTES", "20")),
        max_gap=int(os.environ.get("INTERVAL_MAX_MINUTES", "40")),
    )


def _line(c: Course) -> str:
    return f"• {c.begin} — {c.district} — {c.number} — freie Plätze: {c.places}\n  {c.url}"


def format_changes(changes: state.Changes) -> str:
    parts = []
    if changes.freed:
        parts.append(f"✅ Plätze frei geworden — {TOPIC}:\n" + "\n".join(map(_line, changes.freed)))
    if changes.new:
        parts.append(f"🆕 Neue Termine — {TOPIC}:\n" + "\n".join(map(_line, changes.new)))
    parts.append(f"Kurssuche: {SEARCH_URL}")
    return "\n\n".join(parts)


def format_baseline(courses: list[Course]) -> str:
    free = [c for c in courses if c.is_free]
    head = (
        f"👀 VHS-Sprachtest-Watcher gestartet: {len(courses)} Termine, davon {len(free)} mit freien Plätzen."
    )
    return "\n".join([head, *map(_line, free)]) if free else head


def check_once(data_dir: Path, tg: notify.TelegramConfig | None, dry_run: bool) -> None:
    courses = einbuergerung_only(VhsClient().fetch_all())
    state_path = data_dir / "state.json"
    previous = state.load(state_path)

    if previous is None:
        message = format_baseline(courses)
    else:
        changes = state.diff(previous, courses)
        message = format_changes(changes) if changes else None

    for c in courses:
        log.info("  %s | %s | %s | %s", c.begin, c.district, c.number, c.places)

    if message:
        if dry_run or tg is None:
            print("---- would send ----\n" + message)
        else:
            notify.send(tg, message)
    else:
        log.info("no new dates or freed places")

    if not dry_run:
        state.save(state_path, courses)


def error_summary(exc: BaseException) -> str:
    lines = "".join(traceback.format_exception(exc)).strip().splitlines()
    return "\n".join(lines[-6:])[-1500:]


class FailureTracker:
    """Decides which failed/recovered checks are worth a Telegram message."""

    def __init__(self) -> None:
        self.count = 0

    def failed(self, exc: BaseException) -> str | None:
        self.count += 1
        if self.count != 1 and self.count % REMIND_EVERY != 0:
            return None
        head = (
            "⚠️ VHS-Watcher: Prüfung fehlgeschlagen"
            if self.count == 1
            else (f"⚠️ VHS-Watcher: weiterhin Fehler ({self.count} Prüfungen in Folge)")
        )
        return f"{head}\n\n{error_summary(exc)}"

    def succeeded(self) -> str | None:
        message = (
            f"✅ VHS-Watcher: wieder OK nach {self.count} fehlgeschlagenen Prüfungen." if self.count else None
        )
        self.count = 0
        return message


def alert(tg: notify.TelegramConfig, text: str) -> None:
    """Best effort: an alert that cannot be delivered is logged, never raised."""
    try:
        notify.send(tg, text)
    except Exception:
        log.exception("could not deliver alert to Telegram")


def crash_alert_allowed(data_dir: Path, now: float) -> bool:
    marker = data_dir / "last_crash_alert"
    try:
        if marker.exists() and now - marker.stat().st_mtime < CRASH_ALERT_MIN_GAP_S:
            return False
        marker.touch()
    except OSError:
        log.exception("crash-alert marker unusable; alerting anyway")
    return True


def run_forever(data_dir: Path, tg: notify.TelegramConfig, sched: Schedule) -> None:
    rng = random.Random()
    failures = FailureTracker()
    now = datetime.now(TZ)
    next_at = now if sched.in_window(now) else sched.next_window_start(now, rng)
    while True:
        delay = (next_at - datetime.now(TZ)).total_seconds()
        log.info("next check at %s", next_at.strftime("%Y-%m-%d %H:%M %Z"))
        if delay > 0:
            time.sleep(delay)
        try:
            check_once(data_dir, tg, dry_run=False)
            message = failures.succeeded()
        except Exception as exc:
            log.exception("check failed (%d in a row)", failures.count + 1)
            message = failures.failed(exc)
        if message:
            alert(tg, message)
        next_at = sched.next_run(datetime.now(TZ), rng)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="watcher")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run", help="loop: check ~every 30 min between the window hours (default)")
    check = sub.add_parser("check", help="one check now")
    check.add_argument("--dry-run", action="store_true", help="print, don't send or save state")
    sub.add_parser("login", help="interactive Telegram login; lists your groups' IDs")
    sub.add_parser("test-message", help="send one test message to TELEGRAM_CHAT")
    args = parser.parse_args()

    data_dir = Path(os.environ.get("DATA_DIR", "/data"))
    cmd = args.cmd or "run"
    if cmd == "check" and args.dry_run:
        check_once(data_dir, None, dry_run=True)
        return

    tg = telegram_config()
    if cmd == "login":
        notify.login(tg)
        return
    if not tg.chat:
        sys.exit("TELEGRAM_CHAT is not set — run `login` to list your group IDs")
    if cmd == "test-message":
        notify.send(tg, "🧪 VHS-Sprachtest-Watcher: Testnachricht — Telegram funktioniert.")
    elif cmd == "check":
        check_once(data_dir, tg, dry_run=False)
    else:
        try:
            run_forever(data_dir, tg, schedule_from_env())
        except Exception as exc:
            log.exception("watcher crashed")
            if crash_alert_allowed(data_dir, time.time()):
                alert(tg, f"💥 VHS-Watcher abgestürzt — Container startet neu.\n\n{error_summary(exc)}")
            raise
