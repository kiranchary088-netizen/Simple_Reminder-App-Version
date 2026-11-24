#!/usr/bin/env python3
"""
Simple Reminder List - Desktop App (v4.0, live edition)
FutureReady Hack - Project #109

A friendly desktop (GUI) version of the terminal Reminder List.
Built with Tkinter only, so it needs NO extra installs (Python 3.10+).

What it does
  * Add / edit / delete / complete reminders with live input validation
  * Automatic status: Overdue / Due today / Upcoming / Completed
  * Search + category / priority / status filters, click-to-sort columns
  * Summary tab with charts (pie + bars drawn on Tk canvas) and insights
  * Warning banner and start-up alert for overdue / due-today items
  * Export to CSV, Markdown and plain-text audit log
  * Bulk CSV import with a row-by-row error log
  * JSON storage (same format as the terminal version), safe atomic saves,
    automatic backup if the data file is corrupted
  * Light / dark theme, keyboard shortcuts, right-click menu, undo delete

Live / dynamic features (v4)
  * Live clock, "next reminder" countdown ticking every second
  * Optional due TIME: alarm popup at the exact minute, with Snooze / Done
  * Statuses update by themselves (a 5 pm task turns Overdue at 5 pm)
  * Repeating reminders (daily / weekly / monthly) create their next one when done
  * Quick-add bar understands plain English:  "Submit report tomorrow 5pm !high #work"
  * Animated counters, progress bar and charts

Run:
    python reminder_app.py
"""

from __future__ import annotations

import calendar
import csv
import json
import logging
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from typing import Any, Optional

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter import font as tkfont
except ImportError:  # pragma: no cover
    print("Tkinter is not installed.")
    print("  Windows/macOS: reinstall Python from python.org (tick 'tcl/tk').")
    print("  Linux        : sudo apt install python3-tk")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

if getattr(sys, "frozen", False):          # when packed with PyInstaller
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

DATA_FILE = BASE_DIR / "reminders.json"
SAMPLE_FILE = BASE_DIR / "sample_reminders.json"
SETTINGS_FILE = BASE_DIR / "app_settings.json"
LOG_FILE = BASE_DIR / "reminder_app.log"
IMPORT_LOG = BASE_DIR / "import_errors.log"

APP_NAME = "Simple Reminder List"
APP_VERSION = "4.0"

CATEGORIES = ["Work", "Personal", "Health", "Finance", "Education", "Other"]
PRIORITIES = ["High", "Medium", "Low"]
STATUSES = ["Overdue", "Due today", "Upcoming", "Completed"]
STATUS_FILTERS = ["All", "Active", "Overdue", "Due today", "Upcoming", "Completed"]
REPEATS = ["None", "Daily", "Weekly", "Monthly"]
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y")
MAX_TITLE = 100
MAX_CATEGORY = 30
CHART_W, CHART_H = 340, 240

logger = logging.getLogger("reminder_app")


def setup_logging() -> None:
    try:
        logging.basicConfig(
            filename=LOG_FILE, level=logging.INFO, encoding="utf-8",
            format="%(asctime)s | %(levelname)-7s | %(message)s",
        )
    except OSError:
        pass  # logging is optional - never stop the app for it


# ===========================================================================
# CORE LOGIC (no GUI code in this section - easy to test)
# ===========================================================================

def validate_title(raw: str) -> str:
    title = " ".join(str(raw).split())
    if not title:
        raise ValueError("Title cannot be empty.")
    if len(title) > MAX_TITLE:
        raise ValueError(f"Title is too long ({len(title)}/{MAX_TITLE} characters).")
    return title


def validate_category(raw: str) -> str:
    cat = " ".join(str(raw).split())
    if not cat:
        return "Other"
    if len(cat) > MAX_CATEGORY:
        raise ValueError(f"Category is too long (max {MAX_CATEGORY} characters).")
    for known in CATEGORIES:                       # keep spelling consistent
        if known.lower() == cat.lower():
            return known
    return cat[0].upper() + cat[1:]


def validate_priority(raw: str) -> str:
    text = str(raw).strip().lower()
    mapping = {"high": "High", "h": "High", "1": "High",
               "medium": "Medium", "med": "Medium", "m": "Medium", "2": "Medium",
               "low": "Low", "l": "Low", "3": "Low", "": "Medium"}
    if text not in mapping:
        raise ValueError("Priority must be High, Medium or Low.")
    return mapping[text]


def validate_repeat(raw: str) -> str:
    text = str(raw).strip().lower()
    mapping = {"": "None", "none": "None", "no": "None", "never": "None", "-": "None",
               "daily": "Daily", "day": "Daily", "weekly": "Weekly", "week": "Weekly",
               "monthly": "Monthly", "month": "Monthly"}
    if text not in mapping:
        raise ValueError("Repeat must be None, Daily, Weekly or Monthly.")
    return mapping[text]


def parse_time(raw: str) -> str:
    """Return 'HH:MM' (24h) or '' when empty. Accepts 17:30, 5pm, 5:30 pm, 17."""
    text = str(raw).strip().lower().replace(".", "")
    if not text:
        return ""
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    err = ValueError("Invalid time. Use HH:MM (e.g. 17:30) or 5pm.")
    if not m:
        raise err
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ampm:
        if not 1 <= hour <= 12:
            raise err
        hour = hour % 12 + (12 if ampm == "pm" else 0)
    if hour > 23 or minute > 59:
        raise err
    return f"{hour:02d}:{minute:02d}"


def fmt_span(seconds: float, with_seconds: bool = False) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if with_seconds:
        return f"{hours}h {minutes:02d}m {secs:02d}s" if hours else f"{minutes}m {secs:02d}s"
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes} min"
    return "<1 min"


def next_occurrence(d: date, repeat: str) -> date:
    if repeat == "Daily":
        return d + timedelta(days=1)
    if repeat == "Weekly":
        return d + timedelta(weeks=1)
    if repeat == "Monthly":
        year, month = d.year + d.month // 12, d.month % 12 + 1
        return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))
    return d


def parse_date(raw: str, today: Optional[date] = None) -> date:
    """Accept YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY, 'today', 'tomorrow'."""
    today = today or date.today()
    text = str(raw).strip().lower()
    if not text:
        raise ValueError("Please enter a due date.")
    if text in ("today", "t"):
        return today
    if text in ("tomorrow", "tom"):
        return today + timedelta(days=1)
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        if not 2000 <= parsed.year <= 2100:
            raise ValueError("Year must be between 2000 and 2100.")
        return parsed
    raise ValueError("Invalid date. Use YYYY-MM-DD or DD/MM/YYYY.")


def parse_bool(raw: Any) -> bool:
    return str(raw).strip().lower() in ("true", "yes", "y", "1", "done", "completed")


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


@dataclass
class Reminder:
    id: int
    title: str
    due_date: date
    category: str = "Other"
    priority: str = "Medium"
    is_completed: bool = False
    created_at: str = field(default_factory=now_text)
    due_time: str = ""          # "" (all day) or "HH:MM"
    repeat: str = "None"        # None / Daily / Weekly / Monthly

    def __post_init__(self) -> None:
        self.title = validate_title(self.title)
        self.category = validate_category(self.category)
        self.priority = validate_priority(self.priority)
        self.due_time = parse_time(self.due_time)
        self.repeat = validate_repeat(self.repeat)

    def due_datetime(self) -> datetime:
        if self.due_time:
            hour, minute = (int(x) for x in self.due_time.split(":"))
            return datetime.combine(self.due_date, dtime(hour, minute))
        return datetime.combine(self.due_date, dtime(23, 59, 59))

    def status(self, today: Optional[date] = None) -> str:
        today = today or date.today()
        if self.is_completed:
            return "Completed"
        if self.due_date < today:
            return "Overdue"
        if self.due_date == today:
            # a timed reminder becomes Overdue the moment its time has passed
            if self.due_time and today == date.today() and datetime.now() > self.due_datetime():
                return "Overdue"
            return "Due today"
        return "Upcoming"

    def days_until(self, today: Optional[date] = None) -> int:
        today = today or date.today()
        return (self.due_date - today).days

    def days_text(self, today: Optional[date] = None) -> str:
        state = self.status(today)
        days = self.days_until(today)
        if state == "Completed":
            return "-"
        if state == "Due today":
            if self.due_time:
                return "in " + fmt_span((self.due_datetime() - datetime.now()).total_seconds())
            return "Today"
        if state == "Overdue":
            if days == 0:
                return fmt_span((datetime.now() - self.due_datetime()).total_seconds()) + " late"
            return f"{abs(days)} day{'s' if abs(days) != 1 else ''} late"
        return "Tomorrow" if days == 1 else f"in {days} days"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title,
            "due_date": self.due_date.isoformat(),
            "category": self.category, "priority": self.priority,
            "is_completed": self.is_completed, "created_at": self.created_at,
            "due_time": self.due_time, "repeat": self.repeat,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Reminder":
        return cls(
            id=int(data["id"]),
            title=data["title"],
            due_date=date.fromisoformat(str(data["due_date"])),
            category=data.get("category", "Other"),
            priority=data.get("priority", "Medium"),
            is_completed=bool(data.get("is_completed", False)),
            created_at=str(data.get("created_at") or now_text()),
            due_time=data.get("due_time", "") or "",
            repeat=data.get("repeat", "None") or "None",
        )


class ReminderStore:
    """Holds the reminders in memory and keeps the JSON file in sync."""

    def __init__(self, data_file: Path, sample_file: Optional[Path] = None) -> None:
        self.data_file = Path(data_file)
        self.sample_file = Path(sample_file) if sample_file else None
        self.items: list[Reminder] = []
        self.load_notes: list[str] = []
        self.last_error = ""

    # -- loading ---------------------------------------------------------
    def load(self) -> None:
        self.items = []
        self.load_notes = []
        path = self.data_file
        if not path.exists():
            if self.sample_file and self.sample_file.exists():
                path = self.sample_file
                self.load_notes.append("Loaded the built-in sample reminders.")
            else:
                return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("top level must be a list")
        except (OSError, ValueError) as exc:      # JSONDecodeError is a ValueError
            self._backup_corrupt(path, exc)
            return
        skipped = 0
        seen_ids: set[int] = set()
        for entry in raw:
            try:
                item = Reminder.from_dict(entry)
            except (KeyError, ValueError, TypeError):
                skipped += 1
                continue
            if item.id in seen_ids:               # duplicate ids would break edits
                item.id = max(seen_ids) + 1
            seen_ids.add(item.id)
            self.items.append(item)
        if skipped:
            self.load_notes.append(f"Skipped {skipped} invalid entr{'y' if skipped == 1 else 'ies'} in the data file.")
            logger.warning("Skipped %d invalid entries", skipped)

    def _backup_corrupt(self, path: Path, exc: Exception) -> None:
        logger.error("Could not read %s: %s", path, exc)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.stem}.corrupt-{stamp}{path.suffix}")
        try:
            os.replace(path, backup)
            self.load_notes.append(f"Data file was unreadable. A backup was saved as {backup.name}; starting fresh.")
        except OSError:
            self.load_notes.append("Data file was unreadable; starting with an empty list.")

    # -- saving ----------------------------------------------------------
    def save(self) -> bool:
        tmp = self.data_file.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump([r.to_dict() for r in self.items], fh, indent=2, ensure_ascii=False)
            os.replace(tmp, self.data_file)       # atomic: never leaves half-written file
            self.last_error = ""
            return True
        except OSError as exc:
            self.last_error = str(exc)
            logger.exception("Save failed")
            return False

    # -- queries / edits -------------------------------------------------
    def next_id(self) -> int:
        return max((r.id for r in self.items), default=0) + 1

    def get(self, rid: int) -> Optional[Reminder]:
        return next((r for r in self.items if r.id == rid), None)

    def add(self, item: Reminder) -> None:
        self.items.append(item)

    def remove(self, ids: list[int]) -> list[Reminder]:
        gone = [r for r in self.items if r.id in ids]
        self.items = [r for r in self.items if r.id not in ids]
        return gone

    def complete(self, item: Reminder, today: Optional[date] = None) -> Optional[Reminder]:
        """Mark done. A repeating reminder also creates its next occurrence."""
        item.is_completed = True
        if item.repeat == "None":
            return None
        today = today or date.today()
        nxt = next_occurrence(item.due_date, item.repeat)
        while nxt < today:                        # catch up if it was very late
            nxt = next_occurrence(nxt, item.repeat)
        if any(r.title == item.title and r.due_date == nxt and not r.is_completed for r in self.items):
            return None                           # already scheduled (avoids duplicates)
        new = Reminder(self.next_id(), item.title, nxt, item.category, item.priority,
                       False, due_time=item.due_time, repeat=item.repeat)
        self.items.append(new)
        return new

    def categories(self) -> list[str]:
        extra = sorted({r.category for r in self.items} - set(CATEGORIES))
        return CATEGORIES + extra


def filter_reminders(items: list[Reminder], keyword: str = "", category: str = "All",
                     priority: str = "All", status: str = "All",
                     today: Optional[date] = None) -> list[Reminder]:
    keyword = keyword.strip().lower()
    result = []
    for r in items:
        if keyword and keyword not in r.title.lower() and keyword not in r.category.lower():
            continue
        if category != "All" and r.category != category:
            continue
        if priority != "All" and r.priority != priority:
            continue
        state = r.status(today)
        if status == "Active" and state == "Completed":
            continue
        if status in STATUSES and state != status:
            continue
        result.append(r)
    return result


def compute_summary(items: list[Reminder], today: Optional[date] = None) -> dict[str, Any]:
    today = today or date.today()
    total = len(items)
    states = Counter(r.status(today) for r in items)
    active = [r for r in items if not r.is_completed]
    avg_days = round(sum(r.days_until(today) for r in active) / len(active), 1) if active else 0.0
    by_cat = Counter(r.category for r in items)
    by_pri = Counter(r.priority for r in items)
    soonest = sorted(active, key=lambda r: (r.due_date, r.id))
    return {
        "total": total,
        "completed": states["Completed"],
        "overdue": states["Overdue"],
        "due_today": states["Due today"],
        "upcoming": states["Upcoming"],
        "active": len(active),
        "avg_days": avg_days,
        "completion_rate": round(100 * states["Completed"] / total) if total else 0,
        "by_category": dict(by_cat.most_common()),
        "by_priority": {p: by_pri.get(p, 0) for p in PRIORITIES},
        "high_open": sum(1 for r in active if r.priority == "High"),
        "repeating": sum(1 for r in active if r.repeat != "None"),
        "high_overdue": sum(1 for r in active if r.priority == "High" and r.due_date < today),
        "next_7_days": sum(1 for r in active if 0 <= r.days_until(today) <= 7),
        "earliest": soonest[0] if soonest else None,
        "coming_up": soonest[:6],
    }


def due_alarms(items: list[Reminder], now: datetime, fired: set, snoozed: dict) -> list[Reminder]:
    """Timed reminders whose alarm should ring right now."""
    ringing = []
    for r in items:
        if r.is_completed or not r.due_time:
            continue
        until = snoozed.get(r.id)
        if until is not None:
            if now >= until:
                ringing.append(r)
            continue
        if (r.id, r.due_date, r.due_time) in fired:
            continue
        if now >= r.due_datetime():
            ringing.append(r)
    return ringing


_WEEKDAYS = {"monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2,
             "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "friday": 4, "fri": 4,
             "saturday": 5, "sat": 5, "sunday": 6, "sun": 6}


def parse_quick_add(text: str, now: Optional[datetime] = None) -> dict[str, Any]:
    """Understand a plain-English line such as
       'Submit report tomorrow 5pm !high #work'  or  'Gym every day 6am'.
    Never raises: always returns title/due/time/priority/category/repeat."""
    now = now or datetime.now()
    today = now.date()
    rest = " " + str(text).strip() + " "
    out: dict[str, Any] = {"title": "", "due": None, "time": "", "priority": "Medium",
                           "category": "Other", "repeat": "None"}

    def take(pattern: str):
        nonlocal rest
        m = re.search(pattern, rest, re.IGNORECASE)
        if m:
            rest = rest[:m.start()] + " " + rest[m.end():]
        return m

    m = take(r"\s!(high|medium|med|low|h|m|l)\b")
    if m:
        out["priority"] = validate_priority(m.group(1))
    m = take(r"\s#([\w-]+)")
    if m:
        out["category"] = validate_category(m.group(1)[:MAX_CATEGORY])
    m = take(r"\s(every\s+day|daily|every\s+week|weekly|every\s+month|monthly)\b")
    if m:
        word = m.group(1).lower()
        out["repeat"] = "Daily" if word.startswith("daily") or "day" in word else (
            "Weekly" if "week" in word else "Monthly")

    m = take(r"\s(?:on\s+)?(\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{4})\b")
    if m:
        try:
            out["due"] = parse_date(m.group(1), today)
        except ValueError:
            pass
    m = take(r"\sin\s+(\d+)\s*(minutes?|mins?|hours?|hrs?|h|days?|weeks?)\b")
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        if unit.startswith(("min", "h")):
            target = now + (timedelta(minutes=n) if unit.startswith("min") else timedelta(hours=n))
            out["due"], out["time"] = target.date(), target.strftime("%H:%M")
        else:
            out["due"] = today + timedelta(days=n * (7 if unit.startswith("week") else 1))
    if out["due"] is None:
        m = take(r"\s(today|tonight|tomorrow|tmrw|tom)\b")
        if m:
            out["due"] = today + timedelta(days=1 if m.group(1).lower() in ("tomorrow", "tmrw", "tom") else 0)
    if out["due"] is None:
        m = take(r"\s(?:on\s+|next\s+)?(" + "|".join(sorted(_WEEKDAYS, key=len, reverse=True)) + r")\b")
        if m:
            out["due"] = today + timedelta(days=(_WEEKDAYS[m.group(1).lower()] - today.weekday()) % 7 or 7)
    if not out["time"]:
        m = take(r"\s(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)|\d{1,2}:\d{2})(?=\s)")
        if m:
            try:
                out["time"] = parse_time(m.group(1))
            except ValueError:
                pass
    if out["due"] is None:
        if out["time"] and out["time"] <= now.strftime("%H:%M"):
            out["due"] = today + timedelta(days=1)       # "5pm" said after 5pm means tomorrow
        else:
            out["due"] = today
    title = " ".join(rest.split())
    title = re.sub(r"\s+(on|at|by|due|for|in)$", "", title, flags=re.IGNORECASE)
    out["title"] = title
    return out


# -- export / import --------------------------------------------------------

CSV_HEADER = ["id", "title", "due_date", "category", "priority",
              "status", "is_completed", "created_at", "due_time", "repeat"]


def _due_text(r: Reminder) -> str:
    return r.due_date.isoformat() + (f" {r.due_time}" if r.due_time else "")


def _sorted(items: list[Reminder]) -> list[Reminder]:
    return sorted(items, key=lambda r: (r.due_date, r.id))


def export_csv(items: list[Reminder], path: Path, today: Optional[date] = None) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_HEADER)
        for r in _sorted(items):
            writer.writerow([r.id, r.title, r.due_date.isoformat(), r.category, r.priority,
                             r.status(today), r.is_completed, r.created_at, r.due_time, r.repeat])


def export_markdown(items: list[Reminder], path: Path, today: Optional[date] = None) -> None:
    today = today or date.today()
    s = compute_summary(items, today)
    lines = [
        f"# {APP_NAME} - Report",
        f"_Generated on {today:%d %B %Y}_", "",
        "## Summary", "",
        "| Metric | Value |", "|---|---|",
        f"| Total reminders | {s['total']} |",
        f"| Completed | {s['completed']} ({s['completion_rate']}%) |",
        f"| Overdue | {s['overdue']} |",
        f"| Due today | {s['due_today']} |",
        f"| Upcoming | {s['upcoming']} |",
        f"| Avg. days to due (active) | {s['avg_days']} |", "",
        "## Reminders", "",
        "| ID | Title | Due | Status | Priority | Category |",
        "|---:|---|---|---|---|---|",
    ]
    for r in _sorted(items):
        title = r.title.replace("|", "\\|")
        lines.append(f"| {r.id} | {title} | {_due_text(r)} | {r.status(today)} | {r.priority} | {r.category} |")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_text(items: list[Reminder], path: Path, today: Optional[date] = None) -> None:
    today = today or date.today()
    s = compute_summary(items, today)
    lines = [
        f"{APP_NAME.upper()} - AUDIT LOG",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M}", "=" * 78,
        f"Total {s['total']} | Completed {s['completed']} | Overdue {s['overdue']} | "
        f"Due today {s['due_today']} | Upcoming {s['upcoming']}",
    ]
    if s["overdue"]:
        lines.append(f"WARNING: {s['overdue']} reminder(s) are overdue "
                     f"({s['high_overdue']} of them high priority).")
    lines += ["-" * 78, f"{'ID':>3}  {'Due':<16}  {'Status':<10}  {'Priority':<8}  {'Category':<10}  Title", "-" * 78]
    for r in _sorted(items):
        lines.append(f"{r.id:>3}  {_due_text(r):<16}  {r.status(today):<10}  "
                     f"{r.priority:<8}  {r.category[:10]:<10}  {r.title}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def import_csv(path: Path, existing: list[Reminder], start_id: int) -> tuple[list[Reminder], list[str], int]:
    """Read a CSV file. Returns (new reminders, error messages, duplicates skipped).
    Required columns: title, due_date. Optional: category, priority, is_completed, due_time, repeat."""
    new_items: list[Reminder] = []
    errors: list[str] = []
    duplicates = 0
    known = {(r.title.lower(), r.due_date) for r in existing}
    next_id = start_id
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError("The file is empty.")
        reader.fieldnames = [str(n).strip().lower() for n in reader.fieldnames]
        missing = {"title", "due_date"} - set(reader.fieldnames)
        if missing:
            raise ValueError("Missing required column(s): " + ", ".join(sorted(missing)))
        for row_no, row in enumerate(reader, start=2):      # row 1 is the header
            try:
                title = validate_title(row.get("title") or "")
                due = parse_date(row.get("due_date") or "")
                item = Reminder(
                    id=next_id, title=title, due_date=due,
                    category=validate_category(row.get("category") or ""),
                    priority=validate_priority(row.get("priority") or ""),
                    is_completed=parse_bool(row.get("is_completed") or ""),
                    due_time=parse_time(row.get("due_time") or ""),
                    repeat=validate_repeat(row.get("repeat") or ""),
                )
            except ValueError as exc:
                errors.append(f"Row {row_no}: {exc}")
                continue
            key = (item.title.lower(), item.due_date)
            if key in known:
                duplicates += 1
                continue
            known.add(key)
            new_items.append(item)
            next_id += 1
    return new_items, errors, duplicates


# ===========================================================================
# THEMES
# ===========================================================================

LIGHT = dict(
    bg="#f3f4f8", card="#ffffff", fg="#1f2937", muted="#6b7280", border="#e1e4ec",
    accent="#4f46e5", accent_hover="#4338ca", accent_fg="#ffffff",
    entry_bg="#ffffff", select="#dbe0ff",
    overdue="#dc2626", today="#d97706", upcoming="#2563eb", done="#16a34a",
    row_overdue="#fdecec", row_today="#fff5dc", row_done="#9ca3af",
    banner_bg="#fee2e2", banner_fg="#991b1b",
)
DARK = dict(
    bg="#14161f", card="#1d2030", fg="#e5e7eb", muted="#9ca3af", border="#2d3147",
    accent="#7c83ff", accent_hover="#9aa0ff", accent_fg="#10121a",
    entry_bg="#252940", select="#3a3f66",
    overdue="#f87171", today="#fbbf24", upcoming="#60a5fa", done="#4ade80",
    row_overdue="#3a2024", row_today="#38301a", row_done="#6b7280",
    banner_bg="#4a1d22", banner_fg="#fecaca",
)

STATUS_COLOR_KEY = {"Overdue": "overdue", "Due today": "today",
                    "Upcoming": "upcoming", "Completed": "done"}
PRIORITY_COLOR_KEY = {"High": "overdue", "Medium": "today", "Low": "muted"}


def load_settings() -> dict[str, Any]:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data: dict[str, Any]) -> None:
    try:
        SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


# ===========================================================================
# GUI
# ===========================================================================

class ReminderApp:
    COLUMNS = (  # (key, heading, width, anchor)
        ("id", "ID", 40, "center"),
        ("title", "Title", 240, "w"),
        ("due", "Due", 140, "center"),
        ("when", "When", 90, "center"),
        ("status", "Status", 85, "center"),
        ("priority", "Priority", 70, "center"),
        ("category", "Category", 85, "center"),
        ("repeat", "Repeat", 65, "center"),
    )
    QUICK_HELP = "Try:  Submit report tomorrow 5pm !high #work    |    Gym every day 6am    |    Call mom in 2 hours"

    def __init__(self, root: tk.Tk, store: Optional[ReminderStore] = None) -> None:
        self.root = root
        self.store = store or ReminderStore(DATA_FILE, SAMPLE_FILE)
        self.store.load()
        self.settings = load_settings()
        self.theme_name = self.settings.get("theme", "light")
        self.p = DARK if self.theme_name == "dark" else LIGHT

        self.editing_id: Optional[int] = None
        self.sort_key = "due"
        self.sort_reverse = False
        self.undo_stack: list[list[Reminder]] = []
        self.last_day = date.today()
        self.flash_job = None
        self.visible: list[Reminder] = []
        self.canvases: list[tk.Canvas] = []

        # live-state
        self.fired: set = set()                 # alarms that already rang
        self.snoozed: dict[int, datetime] = {}  # reminder id -> ring again at
        self.alarm_windows: list[Any] = []
        self._row_state: dict[int, str] = {}
        self._stat_shown: dict[str, int] = {}
        self._stat_jobs: dict[str, Any] = {}
        self._anim_job = None
        self._chart_sig = None
        self._chart_cache: Optional[tuple] = None
        self._progress_val = 0.0
        self._progress_job = None

        # form + filter variables
        self.title_var = tk.StringVar()
        self.date_var = tk.StringVar()
        self.time_var = tk.StringVar()
        self.repeat_var = tk.StringVar(value="None")
        self.cat_var = tk.StringVar(value="Other")
        self.pri_var = tk.StringVar(value="Medium")
        self.form_error = tk.StringVar()
        self.date_hint = tk.StringVar()
        self.search_var = tk.StringVar()
        self.cat_filter = tk.StringVar(value="All")
        self.pri_filter = tk.StringVar(value="All")
        self.status_filter = tk.StringVar(value="All")
        self.count_var = tk.StringVar()
        self.flash_var = tk.StringVar()
        self.banner_var = tk.StringVar()
        self.clock_var = tk.StringVar()
        self.next_var = tk.StringVar()
        self.quick_var = tk.StringVar()
        self.quick_preview = tk.StringVar(value=self.QUICK_HELP)
        self.progress_text = tk.StringVar()
        self.stat_vars = {k: tk.StringVar(value="0") for k in
                          ("total", "overdue", "due_today", "upcoming", "completed")}
        self.insight_var = tk.StringVar()
        self.coming_var = tk.StringVar()

        root.title(APP_NAME)
        root.geometry("1200x780")
        root.minsize(1060, 700)

        self.style = ttk.Style(root)
        self._setup_fonts()
        self._build_menu()
        self._build_ui()
        self.apply_theme()
        self.clear_form()
        self._prime_fired()
        self.refresh()
        self._bind_keys()

        for note in self.store.load_notes:
            self.flash(note, 6000)
        root.after(700, self.startup_alert)
        self._live_tick()                      # starts the 1-second heartbeat

    # ------------------------------------------------------------------ fonts
    def _setup_fonts(self) -> None:
        base = tkfont.nametofont("TkDefaultFont")
        base.configure(size=10)
        family = base.actual("family")
        self.font_title = (family, 20, "bold")
        self.font_big = (family, 24, "bold")
        self.font_h2 = (family, 12, "bold")
        self.font_small = (family, 9)
        try:
            tkfont.nametofont("TkTextFont").configure(size=10)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ menu
    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Import from CSV...", command=self.import_from_csv)
        file_menu.add_separator()
        file_menu.add_command(label="Export as CSV...", accelerator="Ctrl+E",
                              command=lambda: self.export("csv"))
        file_menu.add_command(label="Export as Markdown report...",
                              command=lambda: self.export("md"))
        file_menu.add_command(label="Export as text audit log...",
                              command=lambda: self.export("txt"))
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="New reminder (form)", accelerator="Ctrl+N", command=self.focus_new)
        edit_menu.add_command(label="Quick add (type a sentence)", accelerator="Ctrl+K",
                              command=self.focus_quick)
        edit_menu.add_command(label="Toggle complete", command=self.toggle_selected)
        edit_menu.add_command(label="Snooze selected 1 hour", command=self.snooze_selected)
        edit_menu.add_command(label="Delete selected", command=self.delete_selected)
        edit_menu.add_command(label="Undo delete", accelerator="Ctrl+Z", command=self.undo_delete)
        menubar.add_cascade(label="Edit", menu=edit_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Toggle dark / light theme", accelerator="Ctrl+T",
                              command=self.toggle_theme)
        view_menu.add_command(label="Clear all filters", command=self.clear_filters)
        menubar.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Keyboard shortcuts", command=self.show_shortcuts)
        help_menu.add_command(label="Quick-add examples", command=self.show_quick_help)
        help_menu.add_command(label="Add demo alarm (rings in ~1 minute)", command=self.add_demo_alarm)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menubar)

    # ------------------------------------------------------------------ layout
    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, style="App.TFrame", padding=(16, 12, 16, 6))
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer, style="App.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text="Simple Reminder List", style="Title.TLabel").pack(side="left")
        self.theme_btn = ttk.Button(header, text="Dark mode", style="Ghost.TButton",
                                    command=self.toggle_theme)
        self.theme_btn.pack(side="right")
        ttk.Label(header, textvariable=self.clock_var, style="Clock.TLabel").pack(side="right", padx=14)
        ttk.Label(outer, textvariable=self.next_var, style="Next.TLabel").pack(anchor="w", pady=(0, 2))

        banner_slot = ttk.Frame(outer, style="App.TFrame")   # keeps the banner in a fixed place
        banner_slot.pack(fill="x")
        self.banner = tk.Label(banner_slot, textvariable=self.banner_var, anchor="w",
                               padx=12, pady=6, cursor="hand2")
        self.banner.bind("<Button-1>", lambda _e: self.quick_filter("Overdue"))

        # stat cards
        cards = ttk.Frame(outer, style="App.TFrame")
        cards.pack(fill="x", pady=(8, 6))
        card_defs = (("total", "Total", "All", "total"),
                     ("overdue", "Overdue", "Overdue", "overdue"),
                     ("due_today", "Due today", "Due today", "today"),
                     ("upcoming", "Upcoming", "Upcoming", "upcoming"),
                     ("completed", "Completed", "Completed", "done"))
        for i, (key, label, flt, color) in enumerate(card_defs):
            cards.columnconfigure(i, weight=1, uniform="cards")
            card = ttk.Frame(cards, style="Card.TFrame", padding=(14, 8))
            card.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))
            num = ttk.Label(card, textvariable=self.stat_vars[key], style=f"{color}.Num.TLabel")
            num.pack(anchor="w")
            cap = ttk.Label(card, text=label + "  (click to filter)", style="CardCap.TLabel")
            cap.pack(anchor="w")
            for w in (card, num, cap):
                w.bind("<Button-1>", lambda _e, f=flt: self.quick_filter(f))
                w.configure(cursor="hand2")

        prog = ttk.Frame(outer, style="App.TFrame")
        prog.pack(fill="x", pady=(0, 6))
        ttk.Label(prog, textvariable=self.progress_text, style="Sub.TLabel").pack(anchor="w")
        self.progress = ttk.Progressbar(prog, maximum=100, mode="determinate")
        self.progress.pack(fill="x", pady=(3, 0))

        # quick add bar
        quick = ttk.Frame(outer, style="App.TFrame")
        quick.pack(fill="x", pady=(0, 8))
        quick.columnconfigure(1, weight=1)
        ttk.Label(quick, text="Quick add", style="Sub.TLabel").grid(row=0, column=0, padx=(0, 8))
        self.quick_entry = ttk.Entry(quick, textvariable=self.quick_var)
        self.quick_entry.grid(row=0, column=1, sticky="ew")
        ttk.Button(quick, text="Add", style="Accent.TButton", command=self.quick_add).grid(
            row=0, column=2, padx=(8, 0))
        ttk.Label(quick, textvariable=self.quick_preview, style="BgHint.TLabel").grid(
            row=1, column=1, sticky="w", pady=(2, 0))
        self.quick_entry.bind("<Return>", lambda _e: self.quick_add())
        self.quick_var.trace_add("write", lambda *_: self._update_quick_preview())

        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True)
        tab_list = ttk.Frame(self.notebook, style="App.TFrame", padding=(0, 10, 0, 0))
        tab_sum = ttk.Frame(self.notebook, style="App.TFrame", padding=(0, 10, 0, 0))
        self.notebook.add(tab_list, text="  Reminders  ")
        self.notebook.add(tab_sum, text="  Summary & Charts  ")

        self._build_list_tab(tab_list)
        self._build_summary_tab(tab_sum)
        self.notebook.bind("<<NotebookTabChanged>>", lambda _e: self.refresh_summary(force_animate=True))

        status = ttk.Frame(self.root, style="Status.TFrame", padding=(16, 4))
        status.pack(fill="x", side="bottom")
        ttk.Label(status, textvariable=self.flash_var, style="Status.TLabel").pack(side="left")
        ttk.Label(status, text=f"Data: {self.store.data_file.name}", style="Status.TLabel").pack(side="right")

    def _build_list_tab(self, tab: ttk.Frame) -> None:
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(0, weight=1)

        # ---- form card
        form = ttk.Frame(tab, style="Card.TFrame", padding=16)
        form.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        self.form_heading = ttk.Label(form, text="Add reminder", style="H2.TLabel")
        self.form_heading.pack(anchor="w", pady=(0, 8))

        ttk.Label(form, text="Title", style="Field.TLabel").pack(anchor="w")
        self.title_entry = ttk.Entry(form, textvariable=self.title_var, width=32)
        self.title_entry.pack(fill="x", pady=(2, 8))

        ttk.Label(form, text="Due date", style="Field.TLabel").pack(anchor="w")
        self.date_entry = ttk.Entry(form, textvariable=self.date_var, width=32)
        self.date_entry.pack(fill="x", pady=(2, 2))
        ttk.Label(form, textvariable=self.date_hint, style="Hint.TLabel").pack(anchor="w")
        quick = ttk.Frame(form, style="Card.TFrame")
        quick.pack(fill="x", pady=(4, 8))
        for text, days in (("Today", 0), ("Tomorrow", 1), ("+1 week", 7)):
            ttk.Button(quick, text=text, style="Small.TButton",
                       command=lambda d=days: self.set_quick_date(d)).pack(side="left", padx=(0, 6))

        row2 = ttk.Frame(form, style="Card.TFrame")
        row2.pack(fill="x", pady=(0, 8))
        row2.columnconfigure(0, weight=1)
        row2.columnconfigure(1, weight=1)
        ttk.Label(row2, text="Time (e.g. 17:30, 5pm)", style="Field.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(row2, text="Repeat", style="Field.TLabel").grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.time_entry = ttk.Entry(row2, textvariable=self.time_var, width=12)
        self.time_entry.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        ttk.Combobox(row2, textvariable=self.repeat_var, values=REPEATS, state="readonly",
                     width=10).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(2, 0))

        ttk.Label(form, text="Category", style="Field.TLabel").pack(anchor="w")
        self.cat_box = ttk.Combobox(form, textvariable=self.cat_var, values=self.store.categories(), width=29)
        self.cat_box.pack(fill="x", pady=(2, 8))

        ttk.Label(form, text="Priority", style="Field.TLabel").pack(anchor="w")
        pri_row = ttk.Frame(form, style="Card.TFrame")
        pri_row.pack(fill="x", pady=(2, 8))
        for name in PRIORITIES:
            ttk.Radiobutton(pri_row, text=name, value=name, variable=self.pri_var,
                            style="Card.TRadiobutton").pack(side="left", padx=(0, 10))

        ttk.Label(form, textvariable=self.form_error, style="Error.TLabel",
                  wraplength=260, justify="left").pack(anchor="w", pady=(0, 6))
        self.submit_btn = ttk.Button(form, text="Add reminder", style="Accent.TButton", command=self.submit)
        self.submit_btn.pack(fill="x")
        self.cancel_btn = ttk.Button(form, text="Cancel edit", style="Ghost.TButton", command=self.cancel_edit)
        # (cancel button is only packed while editing)

        for entry in (self.title_entry, self.date_entry, self.time_entry):
            entry.bind("<Return>", lambda _e: self.submit())
        self.date_var.trace_add("write", lambda *_: self._update_date_hint())

        # ---- list side
        right = ttk.Frame(tab, style="App.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        bar = ttk.Frame(right, style="App.TFrame")
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(bar, text="Search", style="Sub.TLabel").pack(side="left")
        self.search_entry = ttk.Entry(bar, textvariable=self.search_var, width=20)
        self.search_entry.pack(side="left", padx=(6, 10))
        ttk.Label(bar, text="Category", style="Sub.TLabel").pack(side="left")
        self.cat_filter_box = ttk.Combobox(bar, textvariable=self.cat_filter, state="readonly",
                                           width=10, values=["All"] + self.store.categories())
        self.cat_filter_box.pack(side="left", padx=(6, 8))
        ttk.Label(bar, text="Priority", style="Sub.TLabel").pack(side="left")
        ttk.Combobox(bar, textvariable=self.pri_filter, state="readonly", width=8,
                     values=["All"] + PRIORITIES).pack(side="left", padx=(6, 8))
        ttk.Label(bar, text="Status", style="Sub.TLabel").pack(side="left")
        ttk.Combobox(bar, textvariable=self.status_filter, state="readonly", width=10,
                     values=STATUS_FILTERS).pack(side="left", padx=(6, 8))
        ttk.Button(bar, text="Clear", style="Small.TButton", command=self.clear_filters).pack(side="left")

        for var in (self.search_var, self.cat_filter, self.pri_filter, self.status_filter):
            var.trace_add("write", lambda *_: self.refresh())

        tree_frame = ttk.Frame(right, style="Card.TFrame")
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(tree_frame, columns=[c[0] for c in self.COLUMNS],
                                 show="headings", selectmode="extended")
        for key, heading, width, anchor in self.COLUMNS:
            self.tree.heading(key, text=heading, command=lambda k=key: self.sort_by(k))
            self.tree.column(key, width=width, anchor=anchor, stretch=(key == "title"), minwidth=40)
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        actions = ttk.Frame(right, style="App.TFrame")
        actions.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(actions, text="Mark done / undone", style="Small.TButton",
                   command=self.toggle_selected).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Edit", style="Small.TButton",
                   command=self.edit_selected).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Snooze 1h", style="Small.TButton",
                   command=self.snooze_selected).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Delete", style="Small.TButton",
                   command=self.delete_selected).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Undo delete", style="Small.TButton",
                   command=self.undo_delete).pack(side="left")
        ttk.Label(actions, textvariable=self.count_var, style="Sub.TLabel").pack(side="right")

        # context menu
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Edit", command=self.edit_selected)
        self.menu.add_command(label="Mark done / undone", command=self.toggle_selected)
        self.menu.add_command(label="Snooze 1 hour", command=self.snooze_selected)
        self.menu.add_separator()
        self.menu.add_command(label="Delete", command=self.delete_selected)

        self.tree.bind("<Double-1>", lambda _e: self.edit_selected())
        self.tree.bind("<Delete>", lambda _e: self.delete_selected())
        self.tree.bind("<space>", lambda _e: (self.toggle_selected(), "break")[1])
        self.tree.bind("<Button-3>", self._popup)
        self.tree.bind("<Button-2>", self._popup)

    def _build_summary_tab(self, tab: ttk.Frame) -> None:
        for col in range(3):
            tab.columnconfigure(col, weight=1, uniform="charts")
        self.status_canvas = self._chart_card(tab, 0, "Status breakdown")
        self.cat_canvas = self._chart_card(tab, 1, "By category")
        self.pri_canvas = self._chart_card(tab, 2, "By priority")

        insight = ttk.Frame(tab, style="Card.TFrame", padding=16)
        insight.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(10, 0), padx=(0, 8))
        ttk.Label(insight, text="Key insights", style="H2.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(insight, textvariable=self.insight_var, style="Body.TLabel", justify="left").pack(anchor="w")

        coming = ttk.Frame(tab, style="Card.TFrame", padding=16)
        coming.grid(row=1, column=2, sticky="nsew", pady=(10, 0))
        ttk.Label(coming, text="Coming up next", style="H2.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(coming, textvariable=self.coming_var, style="Body.TLabel", justify="left").pack(anchor="w")
        tab.rowconfigure(1, weight=1)

    def _chart_card(self, parent: ttk.Frame, col: int, title: str) -> tk.Canvas:
        card = ttk.Frame(parent, style="Card.TFrame", padding=(12, 10))
        card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0))
        ttk.Label(card, text=title, style="H2.TLabel").pack(anchor="w")
        canvas = tk.Canvas(card, width=CHART_W, height=CHART_H, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        self.canvases.append(canvas)
        return canvas

    # ------------------------------------------------------------------ theme
    def apply_theme(self) -> None:
        p = self.p
        st = self.style
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        self.root.configure(bg=p["bg"])
        fam = self.font_small[0]

        st.configure(".", background=p["bg"], foreground=p["fg"], font=(fam, 10))
        for name, bg in (("App.TFrame", p["bg"]), ("Card.TFrame", p["card"]), ("Status.TFrame", p["border"])):
            st.configure(name, background=bg)
        st.configure("Title.TLabel", background=p["bg"], foreground=p["fg"], font=self.font_title)
        st.configure("Clock.TLabel", background=p["bg"], foreground=p["fg"], font=(fam, 12, "bold"))
        st.configure("Next.TLabel", background=p["bg"], foreground=p["accent"], font=(fam, 11, "bold"))
        st.configure("Sub.TLabel", background=p["bg"], foreground=p["muted"])
        st.configure("BgHint.TLabel", background=p["bg"], foreground=p["muted"], font=self.font_small)
        st.configure("H2.TLabel", background=p["card"], foreground=p["fg"], font=self.font_h2)
        st.configure("Body.TLabel", background=p["card"], foreground=p["fg"], font=(fam, 11))
        st.configure("Alarm.TLabel", background=p["card"], foreground=p["fg"], font=(fam, 14, "bold"))
        st.configure("Field.TLabel", background=p["card"], foreground=p["muted"], font=(fam, 9, "bold"))
        st.configure("Hint.TLabel", background=p["card"], foreground=p["muted"], font=self.font_small)
        st.configure("Error.TLabel", background=p["card"], foreground=p["overdue"])
        st.configure("CardCap.TLabel", background=p["card"], foreground=p["muted"], font=self.font_small)
        st.configure("Status.TLabel", background=p["border"], foreground=p["muted"], font=self.font_small)
        for color in ("total", "overdue", "today", "upcoming", "done"):
            fg = p["fg"] if color == "total" else p[color]
            st.configure(f"{color}.Num.TLabel", background=p["card"], foreground=fg, font=self.font_big)

        st.configure("TButton", padding=(10, 5), background=p["card"], foreground=p["fg"],
                     bordercolor=p["border"], focuscolor=p["card"], relief="flat")
        st.map("TButton", background=[("active", p["select"])])
        st.configure("Accent.TButton", background=p["accent"], foreground=p["accent_fg"],
                     font=(fam, 10, "bold"), padding=(10, 6), borderwidth=0)
        st.map("Accent.TButton", background=[("active", p["accent_hover"])])
        st.configure("Small.TButton", padding=(8, 4), background=p["card"], foreground=p["fg"])
        st.map("Small.TButton", background=[("active", p["select"])])
        st.configure("Ghost.TButton", background=p["bg"], foreground=p["accent"], borderwidth=0)
        st.map("Ghost.TButton", background=[("active", p["select"])])

        st.configure("Horizontal.TProgressbar", troughcolor=p["border"], background=p["accent"],
                     bordercolor=p["border"], lightcolor=p["accent"], darkcolor=p["accent"], thickness=10)
        st.configure("TEntry", fieldbackground=p["entry_bg"], foreground=p["fg"],
                     bordercolor=p["border"], lightcolor=p["border"], darkcolor=p["border"],
                     insertcolor=p["fg"], padding=5)
        st.configure("TCombobox", fieldbackground=p["entry_bg"], background=p["entry_bg"],
                     foreground=p["fg"], arrowcolor=p["fg"], bordercolor=p["border"],
                     lightcolor=p["border"], darkcolor=p["border"], padding=4)
        st.map("TCombobox", fieldbackground=[("readonly", p["entry_bg"])],
               foreground=[("readonly", p["fg"])], selectbackground=[("readonly", p["entry_bg"])],
               selectforeground=[("readonly", p["fg"])])
        self.root.option_add("*TCombobox*Listbox.background", p["entry_bg"])
        self.root.option_add("*TCombobox*Listbox.foreground", p["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", p["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", p["accent_fg"])
        st.configure("Card.TRadiobutton", background=p["card"], foreground=p["fg"], focuscolor=p["card"])
        st.map("Card.TRadiobutton", background=[("active", p["card"])])

        st.configure("Treeview", background=p["card"], fieldbackground=p["card"], foreground=p["fg"],
                     rowheight=30, borderwidth=0, bordercolor=p["border"])
        st.map("Treeview", background=[("selected", p["select"])], foreground=[("selected", p["fg"])])
        st.configure("Treeview.Heading", background=p["border"], foreground=p["fg"],
                     font=(fam, 10, "bold"), padding=(6, 6), relief="flat")
        st.map("Treeview.Heading", background=[("active", p["select"])])
        st.configure("TNotebook", background=p["bg"], borderwidth=0)
        st.configure("TNotebook.Tab", background=p["bg"], foreground=p["muted"], padding=(8, 6))
        st.map("TNotebook.Tab", background=[("selected", p["card"])], foreground=[("selected", p["accent"])])
        st.configure("Vertical.TScrollbar", background=p["border"], troughcolor=p["card"],
                     bordercolor=p["card"], arrowcolor=p["muted"])

        for canvas in self.canvases:
            canvas.configure(bg=p["card"])
        self.menu.configure(bg=p["card"], fg=p["fg"], activebackground=p["accent"],
                            activeforeground=p["accent_fg"])
        self.banner.configure(bg=p["banner_bg"], fg=p["banner_fg"], font=(fam, 10, "bold"))
        self.tree.tag_configure("Upcoming", foreground=p["fg"])
        self.tree.tag_configure("Overdue", background=p["row_overdue"], foreground=p["overdue"])
        self.tree.tag_configure("Due today", background=p["row_today"], foreground=p["today"])
        self.tree.tag_configure("Completed", foreground=p["row_done"])
        self.theme_btn.configure(text="Light mode" if self.theme_name == "dark" else "Dark mode")

    def toggle_theme(self) -> None:
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        self.p = DARK if self.theme_name == "dark" else LIGHT
        self.settings["theme"] = self.theme_name
        save_settings(self.settings)
        self.apply_theme()
        self._chart_sig = None
        self.refresh()

    # ------------------------------------------------------------------ keys
    def _bind_keys(self) -> None:
        r = self.root
        r.bind("<Control-n>", lambda _e: self.focus_new())
        r.bind("<Control-k>", lambda _e: self.focus_quick())
        r.bind("<Control-f>", lambda _e: self._focus_search())
        r.bind("<Control-e>", lambda _e: self.export("csv"))
        r.bind("<Control-t>", lambda _e: self.toggle_theme())
        r.bind("<Control-z>", lambda _e: self._undo_if_not_typing(_e))
        r.bind("<Escape>", lambda _e: self.cancel_edit())
        r.bind("<F5>", lambda _e: self.refresh())

    def _undo_if_not_typing(self, event: Any) -> None:
        if isinstance(event.widget, (ttk.Entry, tk.Entry)):
            return  # let the text box handle its own undo
        self.undo_delete()

    def _focus_search(self) -> None:
        self.notebook.select(0)
        self.search_entry.focus_set()

    def focus_quick(self) -> None:
        self.quick_entry.focus_set()

    # ------------------------------------------------------------------ LIVE ENGINE
    def _prime_fired(self) -> None:
        """Alarms that are already in the past when the app starts do not ring."""
        for r in self.store.items:
            self._prime_one(r)

    def _prime_one(self, r: Reminder) -> None:
        if r.due_time and r.due_datetime() <= datetime.now():
            self.fired.add((r.id, r.due_date, r.due_time))

    def _live_tick(self) -> None:
        """Runs every second: clock, countdown, auto status changes, alarms."""
        try:
            now = datetime.now()
            self.clock_var.set(now.strftime("%a, %d %b %Y   %H:%M:%S"))
            self.next_var.set(self._next_text(now))
            if now.date() != self.last_day:
                self.last_day = now.date()
                self.refresh()
                self.startup_alert()
            else:
                states = {r.id: r.status() for r in self.store.items}
                if states != self._row_state:
                    self.refresh()                      # a status changed by itself
                elif now.second % 15 == 0:
                    self._update_when_column(now)
            for r in due_alarms(self.store.items, now, self.fired, self.snoozed):
                self.fired.add((r.id, r.due_date, r.due_time))
                self.snoozed.pop(r.id, None)
                self.show_alarm(r)
        except Exception:                               # never let the heartbeat die
            logger.exception("live tick failed")
        finally:
            self.root.after(1000, self._live_tick)

    def _update_when_column(self, now: datetime) -> None:
        for r in self.visible:
            if r.due_time and not r.is_completed and r.due_date == now.date():
                try:
                    self.tree.item(str(r.id), values=self._row_values(r))
                except tk.TclError:
                    pass

    def _next_text(self, now: datetime) -> str:
        upcoming = [r for r in self.store.items if r.status() in ("Due today", "Upcoming")]
        if not upcoming:
            return "Next up: nothing pending"
        nxt = min(upcoming, key=lambda r: (r.due_date, r.due_time or "24:00", r.id))
        name = nxt.title if len(nxt.title) <= 42 else nxt.title[:41] + "..."
        if nxt.due_time and nxt.due_date == now.date():
            left = (nxt.due_datetime() - now).total_seconds()
            return f"Next up: {name}  -  rings in {fmt_span(left, True)}"
        if nxt.due_date == now.date():
            return f"Next up: {name}  -  due today"
        return f"Next up: {name}  -  {nxt.days_text()}"

    def show_alarm(self, r: Reminder) -> None:
        try:
            self.root.bell()
        except Exception:
            pass
        p = self.p
        win = tk.Toplevel(self.root)
        win.title("Reminder due now")
        win.configure(bg=p["card"])
        try:
            win.attributes("-topmost", True)
            win.resizable(False, False)
        except Exception:
            pass
        box = ttk.Frame(win, style="Card.TFrame", padding=18)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text="Reminder due now", style="H2.TLabel").pack(anchor="w")
        ttk.Label(box, text=r.title, style="Alarm.TLabel", wraplength=340,
                  justify="left").pack(anchor="w", pady=(8, 2))
        ttk.Label(box, text=f"{r.category}   |   {r.priority} priority   |   due {r.due_time}",
                  style="Hint.TLabel").pack(anchor="w", pady=(0, 12))
        row = ttk.Frame(box, style="Card.TFrame")
        row.pack(fill="x")

        def close() -> None:
            if win in self.alarm_windows:
                self.alarm_windows.remove(win)
            win.destroy()

        def snooze(minutes: int) -> None:
            self.snoozed[r.id] = datetime.now() + timedelta(minutes=minutes)
            self.flash(f"Snoozed '{r.title}' for {minutes} min.")
            close()

        def done() -> None:
            self.set_completed([r.id], True)
            close()

        ttk.Button(row, text="Snooze 5 min", style="Small.TButton",
                   command=lambda: snooze(5)).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Snooze 1 hour", style="Small.TButton",
                   command=lambda: snooze(60)).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Mark done", style="Accent.TButton", command=done).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Dismiss", style="Small.TButton", command=close).pack(side="left")
        win.protocol("WM_DELETE_WINDOW", close)
        try:                                            # top-right of the main window, staggered
            win.update_idletasks()
            x = self.root.winfo_rootx() + self.root.winfo_width() - win.winfo_reqwidth() - 30
            y = self.root.winfo_rooty() + 70 + 36 * len(self.alarm_windows)
            win.geometry(f"+{x}+{y}")
        except Exception:
            pass
        self.alarm_windows.append(win)
        self.flash(f"ALARM: {r.title}", 8000)

    # ------------------------------------------------------------------ animation helpers
    def _set_stat(self, key: str, target: int) -> None:
        start = self._stat_shown.get(key, 0)
        job = self._stat_jobs.pop(key, None)
        if job is not None:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        if start == target:
            self.stat_vars[key].set(str(target))
            return
        steps = 10

        def step(i: int) -> None:
            value = round(start + (target - start) * i / steps)
            self._stat_shown[key] = value
            self.stat_vars[key].set(str(value))
            if i < steps:
                self._stat_jobs[key] = self.root.after(25, lambda: step(i + 1))

        step(1)

    def _animate_progress(self, target: float) -> None:
        if self._progress_job is not None:
            try:
                self.root.after_cancel(self._progress_job)
            except Exception:
                pass
            self._progress_job = None
        start = self._progress_val
        if abs(target - start) < 0.01:
            return
        steps = 12

        def step(i: int) -> None:
            self._progress_val = start + (target - start) * i / steps
            self.progress.configure(value=self._progress_val)
            if i < steps:
                self._progress_job = self.root.after(22, lambda: step(i + 1))

        step(1)

    def _animate_charts(self) -> None:
        if self._anim_job is not None:
            try:
                self.root.after_cancel(self._anim_job)
            except Exception:
                pass
        frames = 14

        def frame(i: int) -> None:
            t = i / frames
            self._draw_all_charts(1 - (1 - t) ** 3)         # ease-out
            self._anim_job = self.root.after(30, lambda: frame(i + 1)) if i < frames else None

        frame(1)

    # ------------------------------------------------------------------ form
    def set_quick_date(self, days: int) -> None:
        self.date_var.set((date.today() + timedelta(days=days)).isoformat())

    def _update_date_hint(self) -> None:
        raw = self.date_var.get()
        if not raw.strip():
            self.date_hint.set("Use YYYY-MM-DD or DD/MM/YYYY")
            return
        try:
            d = parse_date(raw)
            self.date_hint.set(f"-> {d:%A, %d %B %Y}")
        except ValueError as exc:
            self.date_hint.set(str(exc))

    def _update_quick_preview(self) -> None:
        text = self.quick_var.get().strip()
        if not text:
            self.quick_preview.set(self.QUICK_HELP)
            return
        q = parse_quick_add(text)
        when = f"{q['due']:%a %d %b}" + (f" at {q['time']}" if q["time"] else "")
        bits = [f"'{q['title'] or '(title missing)'}'", when, f"{q['priority']} priority", q["category"]]
        if q["repeat"] != "None":
            bits.append("repeats " + q["repeat"].lower())
        self.quick_preview.set("Will add:  " + "  |  ".join(bits))

    def clear_form(self) -> None:
        self.editing_id = None
        self.title_var.set("")
        self.set_quick_date(1)
        self.time_var.set("")
        self.repeat_var.set("None")
        self.cat_var.set("Other")
        self.pri_var.set("Medium")
        self.form_error.set("")
        self.form_heading.configure(text="Add reminder")
        self.submit_btn.configure(text="Add reminder")
        self.cancel_btn.pack_forget()
        self._update_date_hint()

    def focus_new(self) -> None:
        self.notebook.select(0)
        self.clear_form()
        self.title_entry.focus_set()

    def cancel_edit(self) -> None:
        if self.editing_id is not None:
            self.clear_form()
            self.flash("Edit cancelled.")

    def persist(self) -> bool:
        ok = self.store.save()
        if not ok:
            messagebox.showerror("Could not save",
                                 f"Your change is on screen but could not be saved to disk:\n\n{self.store.last_error}")
        return ok

    def _add_new(self, title: str, due: date, due_time: str, category: str,
                 priority: str, repeat: str) -> Optional[Reminder]:
        if due < date.today():
            if not messagebox.askyesno("Date is in the past",
                                       f"{due:%d %b %Y} has already passed.\nThe reminder will be marked Overdue. Add it anyway?"):
                return None
        item = Reminder(self.store.next_id(), title, due, category, priority,
                        due_time=due_time, repeat=repeat)
        self.store.add(item)
        self._prime_one(item)
        self.persist()
        self.refresh(select=[item.id])
        extra = f" at {item.due_time}" if item.due_time else ""
        self.flash(f"Added '{item.title}' for {item.due_date:%d %b}{extra}.")
        return item

    def submit(self) -> None:
        try:
            title = validate_title(self.title_var.get())
            due = parse_date(self.date_var.get())
            due_time = parse_time(self.time_var.get())
            category = validate_category(self.cat_var.get())
            priority = validate_priority(self.pri_var.get())
            repeat = validate_repeat(self.repeat_var.get())
        except ValueError as exc:
            self.form_error.set(str(exc))
            return
        existing = self.store.get(self.editing_id) if self.editing_id is not None else None
        if self.editing_id is not None and existing is None:
            self.clear_form()
            self.flash("That reminder no longer exists.")
            return
        self.form_error.set("")
        if existing is None:
            if self._add_new(title, due, due_time, category, priority, repeat) is not None:
                self.clear_form()
            return
        if due < date.today() and existing.due_date != due:
            if not messagebox.askyesno("Date is in the past",
                                       f"{due:%d %b %Y} has already passed.\nThe reminder will be marked Overdue. Save anyway?"):
                return
        existing.title, existing.due_date, existing.due_time = title, due, due_time
        existing.category, existing.priority, existing.repeat = category, priority, repeat
        self.snoozed.pop(existing.id, None)
        self._prime_one(existing)
        self.persist()
        self.clear_form()
        self.refresh(select=[existing.id])
        self.flash(f"Updated '{existing.title}'.")

    def quick_add(self) -> None:
        text = self.quick_var.get().strip()
        if not text:
            self.flash("Type a sentence first, e.g. 'Submit report tomorrow 5pm !high'.")
            return
        q = parse_quick_add(text)
        try:
            title = validate_title(q["title"])
        except ValueError as exc:
            self.quick_preview.set(str(exc))
            return
        if self._add_new(title, q["due"], q["time"], q["category"], q["priority"], q["repeat"]) is not None:
            self.quick_var.set("")

    # ------------------------------------------------------------------ list actions
    def _selected_ids(self) -> list[int]:
        return [int(i) for i in self.tree.selection()]

    def edit_selected(self) -> None:
        ids = self._selected_ids()
        if not ids:
            self.flash("Select a reminder to edit first.")
            return
        item = self.store.get(ids[0])
        if item is None:
            return
        self.editing_id = item.id
        self.title_var.set(item.title)
        self.date_var.set(item.due_date.isoformat())
        self.time_var.set(item.due_time)
        self.repeat_var.set(item.repeat)
        self.cat_var.set(item.category)
        self.pri_var.set(item.priority)
        self.form_error.set("")
        self.form_heading.configure(text=f"Edit reminder #{item.id}")
        self.submit_btn.configure(text="Save changes")
        self.cancel_btn.pack(fill="x", pady=(6, 0))
        self.title_entry.focus_set()

    def set_completed(self, ids: list[int], done: bool) -> None:
        items = [r for r in (self.store.get(i) for i in ids) if r]
        spawned: list[Reminder] = []
        for r in items:
            if done and not r.is_completed:
                new = self.store.complete(r)
                if new:
                    spawned.append(new)
            else:
                r.is_completed = done
                if not done:
                    self._prime_one(r)
            self.snoozed.pop(r.id, None)
        self.persist()
        self.refresh(select=ids)
        msg = f"Marked {len(items)} reminder(s) as {'completed' if done else 'not completed'}."
        if spawned:
            msg += f" Next repeat scheduled for {spawned[0].due_date:%d %b}."
        self.flash(msg)

    def toggle_selected(self) -> None:
        ids = self._selected_ids()
        if not ids:
            self.flash("Select one or more reminders first.")
            return
        items = [r for r in (self.store.get(i) for i in ids) if r]
        self.set_completed(ids, not all(r.is_completed for r in items))

    def snooze_selected(self) -> None:
        """Push the selected reminders 1 hour (timed) or 1 day (all-day) into the future."""
        ids = self._selected_ids()
        if not ids:
            self.flash("Select a reminder to snooze first.")
            return
        for rid in ids:
            r = self.store.get(rid)
            if r is None or r.is_completed:
                continue
            if r.due_time:
                target = max(r.due_datetime(), datetime.now()) + timedelta(hours=1)
                r.due_date, r.due_time = target.date(), target.strftime("%H:%M")
            else:
                r.due_date = max(r.due_date, date.today()) + timedelta(days=1)
            self._prime_one(r)
        self.persist()
        self.refresh(select=ids)
        self.flash(f"Snoozed {len(ids)} reminder(s).")

    def delete_selected(self) -> None:
        ids = self._selected_ids()
        if not ids:
            self.flash("Select one or more reminders to delete.")
            return
        names = [self.store.get(i).title for i in ids if self.store.get(i)]
        what = f"'{names[0]}'" if len(names) == 1 else f"{len(names)} reminders"
        if not messagebox.askyesno("Delete", f"Delete {what}?\n(You can undo with Ctrl+Z.)"):
            return
        removed = self.store.remove(ids)
        self.undo_stack.append(removed)
        if self.editing_id in ids:
            self.clear_form()
        self.persist()
        self.refresh()
        self.flash(f"Deleted {len(removed)} reminder(s). Press Ctrl+Z to undo.")

    def undo_delete(self) -> None:
        if not self.undo_stack:
            self.flash("Nothing to undo.")
            return
        restored = self.undo_stack.pop()
        used = {r.id for r in self.store.items}
        for item in restored:
            if item.id in used:
                item.id = self.store.next_id()
            used.add(item.id)
            self.store.add(item)
            self._prime_one(item)
        self.persist()
        self.refresh(select=[r.id for r in restored])
        self.flash(f"Restored {len(restored)} reminder(s).")

    def _popup(self, event: Any) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            if row not in self.tree.selection():
                self.tree.selection_set(row)
            try:
                self.menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.menu.grab_release()

    # ------------------------------------------------------------------ filters & sorting
    def quick_filter(self, status: str) -> None:
        self.notebook.select(0)
        self.search_var.set("")
        self.cat_filter.set("All")
        self.pri_filter.set("All")
        self.status_filter.set(status)

    def clear_filters(self) -> None:
        self.search_var.set("")
        self.cat_filter.set("All")
        self.pri_filter.set("All")
        self.status_filter.set("All")

    def sort_by(self, key: str) -> None:
        if self.sort_key == key:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_key, self.sort_reverse = key, False
        self.refresh()

    def _sort_value(self, r: Reminder, key: str) -> Any:
        order = {"Overdue": 0, "Due today": 1, "Upcoming": 2, "Completed": 3}
        pri = {"High": 0, "Medium": 1, "Low": 2}
        return {
            "id": r.id, "title": r.title.lower(), "due": (r.due_date, r.due_time, r.id),
            "when": (r.due_date, r.due_time, r.id), "status": (order[r.status()], r.due_date),
            "priority": (pri[r.priority], r.due_date), "category": r.category.lower(),
            "repeat": (r.repeat, r.due_date),
        }[key]

    # ------------------------------------------------------------------ refresh
    def _row_values(self, r: Reminder) -> tuple:
        due = f"{r.due_date:%d %b %Y}" + (f"  {r.due_time}" if r.due_time else "")
        return (r.id, r.title, due, r.days_text(), r.status(), r.priority, r.category,
                "-" if r.repeat == "None" else r.repeat)

    def refresh(self, select: Optional[list[int]] = None) -> None:
        keep = set(select) if select else set(self._selected_ids())
        shown = filter_reminders(self.store.items, self.search_var.get(), self.cat_filter.get(),
                                 self.pri_filter.get(), self.status_filter.get())
        shown.sort(key=lambda r: self._sort_value(r, self.sort_key), reverse=self.sort_reverse)
        self.visible = shown
        self._row_state = {r.id: r.status() for r in self.store.items}

        self.tree.delete(*self.tree.get_children())
        for r in shown:
            self.tree.insert("", "end", iid=str(r.id), tags=(self._row_state[r.id],),
                             values=self._row_values(r))
        keep_ids = [str(i) for i in keep if any(r.id == i for r in shown)]
        if keep_ids:
            self.tree.selection_set(keep_ids)
            self.tree.see(keep_ids[0])

        arrow = " \u25b2" if not self.sort_reverse else " \u25bc"
        for key, heading, _w, _a in self.COLUMNS:
            self.tree.heading(key, text=heading + (arrow if key == self.sort_key else ""))

        total = len(self.store.items)
        self.count_var.set(f"Showing {len(shown)} of {total}")
        self.cat_box.configure(values=self.store.categories())
        self.cat_filter_box.configure(values=["All"] + self.store.categories())
        self._refresh_header()
        self.refresh_summary()

    def _refresh_header(self) -> None:
        s = compute_summary(self.store.items)
        for key in self.stat_vars:
            self._set_stat(key, s[key])
        self.progress_text.set(f"Overall progress: {s['completion_rate']}% complete "
                               f"({s['completed']} of {s['total']} done)")
        self._animate_progress(float(s["completion_rate"]))
        if s["overdue"]:
            extra = f"  ({s['high_overdue']} high priority)" if s["high_overdue"] else ""
            self.banner_var.set(f"  \u26a0  {s['overdue']} reminder(s) overdue{extra}. Click to view.")
            self.banner.pack(fill="x", pady=(8, 0))
        else:
            self.banner.pack_forget()
        self.root.title(f"{APP_NAME}" + (f"  -  {s['overdue']} overdue" if s["overdue"] else ""))

    def _charts_visible(self) -> bool:
        try:
            return self.notebook.index(self.notebook.select()) == 1
        except Exception:
            return False

    def refresh_summary(self, force_animate: bool = False) -> None:
        s = compute_summary(self.store.items)
        p = self.p
        slices = [(n, s[k], p[STATUS_COLOR_KEY[n]]) for n, k in
                  (("Overdue", "overdue"), ("Due today", "due_today"),
                   ("Upcoming", "upcoming"), ("Completed", "completed"))]
        cats = list(s["by_category"].items())
        if len(cats) > 7:
            cats = cats[:6] + [("More...", sum(v for _k, v in cats[6:]))]
        cat_bars = [(k, v, p["accent"]) for k, v in cats]
        pri_bars = [(k, s["by_priority"][k], p[PRIORITY_COLOR_KEY[k]]) for k in PRIORITIES]
        self._chart_cache = (slices, cat_bars, pri_bars)

        sig = (tuple((n, v) for n, v, _c in slices), tuple((k, v) for k, v, _c in cat_bars),
               tuple((k, v) for k, v, _c in pri_bars), self.theme_name)
        if self._charts_visible() and (force_animate or sig != self._chart_sig):
            self._chart_sig = sig
            self._animate_charts()
        elif self._anim_job is None:
            self._draw_all_charts(1.0)

        lines = [
            f"Completion rate : {s['completion_rate']}%  ({s['completed']} of {s['total']})",
            f"Active reminders: {s['active']}",
            f"Avg. days to due: {s['avg_days']}  (active only)",
            f"Due in next 7 days: {s['next_7_days']}",
            f"High priority open: {s['high_open']}",
            f"Repeating reminders: {s['repeating']}",
        ]
        if s["by_category"]:
            top = next(iter(s["by_category"].items()))
            lines.append(f"Busiest category: {top[0]} ({top[1]})")
        if s["earliest"]:
            e = s["earliest"]
            lines.append(f"Earliest deadline: {e.due_date:%d %b %Y} - {e.title[:34]}")
        if s["overdue"]:
            lines.append(f"\u26a0 WARNING: {s['overdue']} overdue ({s['high_overdue']} high priority)")
        elif s["total"]:
            lines.append("All caught up - nothing is overdue.")
        self.insight_var.set("\n".join(lines))

        if s["coming_up"]:
            self.coming_var.set("\n".join(
                f"\u2022 {r.due_date:%d %b}{(' ' + r.due_time) if r.due_time else ''}  {r.title[:28]}  ({r.days_text()})"
                for r in s["coming_up"]))
        else:
            self.coming_var.set("Nothing pending. Enjoy!")

    # ------------------------------------------------------------------ charts
    def _draw_all_charts(self, progress: float = 1.0) -> None:
        if not self._chart_cache:
            return
        slices, cat_bars, pri_bars = self._chart_cache
        self._draw_pie(self.status_canvas, slices, progress)
        self._draw_bars(self.cat_canvas, cat_bars, progress)
        self._draw_bars(self.pri_canvas, pri_bars, progress)

    def _draw_pie(self, canvas: tk.Canvas, slices: list[tuple[str, int, str]], progress: float = 1.0) -> None:
        canvas.delete("all")
        total = sum(v for _n, v, _c in slices)
        if total == 0:
            canvas.create_text(CHART_W / 2, CHART_H / 2, text="No data yet", fill=self.p["muted"])
            return
        box = (14, 20, 14 + 170, 20 + 170)
        live = [s for s in slices if s[1] > 0]
        if len(live) == 1 and progress >= 1.0:
            canvas.create_oval(*box, fill=live[0][2], outline=self.p["card"], width=2)
        else:
            start = 90.0
            sweep = min(progress, 0.9999)
            for _n, value, color in live:
                extent = -360.0 * sweep * value / total
                if abs(extent) > 0.01:
                    canvas.create_arc(*box, start=start, extent=extent, fill=color,
                                      outline=self.p["card"], width=2)
                start += extent
        canvas.create_oval(14 + 45, 20 + 45, 14 + 125, 20 + 125, fill=self.p["card"], outline=self.p["card"])
        canvas.create_text(14 + 85, 20 + 78, text=str(round(total * progress)), fill=self.p["fg"], font=self.font_h2)
        canvas.create_text(14 + 85, 20 + 98, text="total", fill=self.p["muted"], font=self.font_small)
        y = 40
        for name, value, color in slices:
            canvas.create_rectangle(206, y, 218, y + 12, fill=color, outline=color)
            pct = round(100 * value / total)
            canvas.create_text(226, y + 6, anchor="w", fill=self.p["fg"], font=self.font_small,
                               text=f"{name}: {value} ({pct}%)")
            y += 30

    def _draw_bars(self, canvas: tk.Canvas, bars: list[tuple[str, int, str]], progress: float = 1.0) -> None:
        canvas.delete("all")
        if not bars or all(v == 0 for _k, v, _c in bars):
            canvas.create_text(CHART_W / 2, CHART_H / 2, text="No data yet", fill=self.p["muted"])
            return
        top = max(v for _k, v, _c in bars) or 1
        x0, max_w, y, step = 92, CHART_W - 92 - 40, 14, 30
        for label, value, color in bars:
            canvas.create_text(x0 - 8, y + 10, anchor="e", text=label[:12], fill=self.p["fg"], font=self.font_small)
            width = int(max(3, max_w * value / top) * progress) if value else 0
            if width:
                canvas.create_rectangle(x0, y, x0 + width, y + 20, fill=color, outline=color)
            canvas.create_text(x0 + width + 6, y + 10, anchor="w", text=str(round(value * progress)),
                               fill=self.p["muted"], font=self.font_small)
            y += step

    # ------------------------------------------------------------------ import / export
    def export(self, kind: str) -> None:
        if not self.store.items:
            messagebox.showinfo("Nothing to export", "There are no reminders yet.")
            return
        spec = {"csv": (".csv", "CSV file", export_csv), "md": (".md", "Markdown", export_markdown),
                "txt": (".txt", "Text file", export_text)}[kind]
        path = filedialog.asksaveasfilename(
            title="Export reminders", defaultextension=spec[0],
            initialfile=f"reminders_{date.today():%Y%m%d}{spec[0]}",
            filetypes=[(spec[1], f"*{spec[0]}"), ("All files", "*.*")])
        if not path:
            return
        try:
            spec[2](self.store.items, Path(path))
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc))
            return
        self.flash(f"Exported {len(self.store.items)} reminders to {Path(path).name}")

    def import_from_csv(self) -> None:
        path = filedialog.askopenfilename(title="Import reminders from CSV",
                                          filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            new_items, errors, dupes = import_csv(Path(path), self.store.items, self.store.next_id())
        except (OSError, ValueError, UnicodeDecodeError, csv.Error) as exc:
            messagebox.showerror("Import failed", f"Could not read the file:\n{exc}")
            return
        for item in new_items:
            self.store.add(item)
            self._prime_one(item)
        if new_items:
            self.persist()
            self.refresh(select=[r.id for r in new_items])
        report = f"Imported: {len(new_items)}\nSkipped duplicates: {dupes}\nRows with errors: {len(errors)}"
        if errors:
            try:
                IMPORT_LOG.write_text("\n".join(errors), encoding="utf-8")
                report += f"\n\nFirst problems:\n" + "\n".join(errors[:8])
                if len(errors) > 8:
                    report += f"\n...and {len(errors) - 8} more (see {IMPORT_LOG.name})"
            except OSError:
                report += "\n\n" + "\n".join(errors[:8])
        messagebox.showinfo("Import finished", report)
        self.flash(f"Imported {len(new_items)} reminder(s) from {Path(path).name}")

    # ------------------------------------------------------------------ misc
    def flash(self, text: str, ms: int = 4000) -> None:
        self.flash_var.set(text)
        if self.flash_job is not None:
            try:
                self.root.after_cancel(self.flash_job)
            except (tk.TclError, ValueError):
                pass
        self.flash_job = self.root.after(ms, lambda: self.flash_var.set(""))

    def startup_alert(self) -> None:
        s = compute_summary(self.store.items)
        if s["overdue"] or s["due_today"]:
            parts = []
            if s["overdue"]:
                parts.append(f"{s['overdue']} overdue")
            if s["due_today"]:
                parts.append(f"{s['due_today']} due today")
            messagebox.showwarning("Reminder alert", "You have " + " and ".join(parts) + ".")

    def add_demo_alarm(self) -> None:
        """Handy for presentations: creates a timed reminder that rings within a minute."""
        when = datetime.now() + timedelta(minutes=1)
        item = Reminder(self.store.next_id(), "Demo alarm - rings in about a minute", when.date(),
                        "Other", "High", due_time=when.strftime("%H:%M"))
        self.store.add(item)                       # not primed on purpose: it must ring
        self.persist()
        self.notebook.select(0)
        self.refresh(select=[item.id])
        self.flash(f"Demo alarm set for {item.due_time}. Watch the countdown at the top!", 7000)

    def show_quick_help(self) -> None:
        messagebox.showinfo("Quick-add examples", (
            "Type a sentence in the Quick add bar and press Enter:\n\n"
            "Submit report tomorrow 5pm !high #work\n"
            "Call mom in 2 hours\n"
            "Gym every day 6am\n"
            "Pay fees 05/12/2026 !high #finance\n"
            "Team meeting friday 10:30\n"
            "Rent monthly\n\n"
            "!high / !med / !low = priority     #name = category\n"
            "daily / weekly / monthly = repeat\n"
            "Words like today, tomorrow, monday, 'in 3 days', '5pm' set the date and time."))

    def show_shortcuts(self) -> None:
        messagebox.showinfo("Keyboard shortcuts", (
            "Ctrl+K   Quick add (type a sentence)\nCtrl+N   New reminder (form)\n"
            "Ctrl+F   Search\nCtrl+E   Export CSV\nCtrl+Z   Undo delete\n"
            "Ctrl+T   Dark / light theme\nF5       Refresh\nEsc      Cancel edit\n\n"
            "In the list:\nDouble-click  Edit\nSpace  Mark done\nDelete  Delete selected\nRight-click  Menu"))

    def show_about(self) -> None:
        messagebox.showinfo("About", f"{APP_NAME} v{APP_VERSION} (live edition)\nFutureReady Hack - Project #109\n\n"
                            "Built with Python + Tkinter (no extra libraries).")


def main() -> None:
    setup_logging()
    try:  # sharper text on high-DPI Windows screens
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    ReminderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
