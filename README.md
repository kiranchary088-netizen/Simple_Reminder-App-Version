# Simple Reminder List - Desktop App v4.0 (Live Edition)
FutureReady Hack - Project #109 | Python 3.10+ | Tkinter only (no pip installs)

## Run
    python reminder_app.py
(Windows: double-click `run_app.bat`.  Linux needs `sudo apt install python3-tk` once.)
Keep `reminder_app.py` and `sample_reminders.json` in the same folder.
Your data is saved to `reminders.json` (same JSON format as the terminal version).

## What makes it dynamic (new in v4)
| Feature | What you see |
|---|---|
| Live clock + "Next up" countdown | Header ticks every second: `rings in 1h 12m 05s` |
| Timed alarms | Pop-up at the exact minute with Snooze 5 min / 1 hour / Mark done / Dismiss + beep |
| Auto status | A 5 pm reminder turns **Overdue** at 5 pm by itself; counters, banner, window title update |
| Repeating reminders | Daily / Weekly / Monthly: marking done creates the next one automatically |
| Quick-add bar | Type `Submit report tomorrow 5pm !high #work` - live preview, Enter to add |
| Animated UI | Counting stat cards, animated progress bar, charts that sweep/grow |
| Snooze | Right-click > Snooze 1 hour on any reminder |
| Live "When" column | `in 2h 15m`, `45 min late`, `Tomorrow`, `3 days late` |

Quick-add words: `today tomorrow monday..sunday`, `in 2 hours`, `in 3 days`, `5pm`, `17:30`,
`05/12/2026`, `2026-12-05`, `!high !med !low`, `#category`, `daily weekly monthly`.

## Original features (still included)
Add/edit/delete, live validation, search + filters, click-to-sort, summary charts,
CSV/Markdown/text export, bulk CSV import with error log, dark/light theme, undo delete,
corrupt-file backup, atomic saves, keyboard shortcuts, right-click menu.

CSV import columns: `title`, `due_date` (required); `category`, `priority`, `is_completed`, `due_time`, `repeat` (optional).

## 3-minute demo script
1. Launch: banner + alert show overdue items; point at the ticking clock and "Next up" countdown.
2. Quick add: type `Call mom in 2 hours !high` -> show live preview -> Enter.
3. Form: enter date `32/13/2026` -> validation message -> fix it.
4. Help > **Add demo alarm** -> within a minute the alarm pops up -> Snooze or Mark done.
5. Mark a repeating reminder done -> the next one appears.
6. Summary tab: animated charts. Toggle dark mode (Ctrl+T).
7. Close and reopen: data persists. File > Export > Markdown.

## Shortcuts
Ctrl+K quick add | Ctrl+N form | Ctrl+F search | Ctrl+E export | Ctrl+Z undo | Ctrl+T theme | Esc cancel
Double-click edit | Space done | Delete delete | Right-click menu

## Make an .exe (optional)
    pip install pyinstaller
    pyinstaller --onefile --windowed reminder_app.py
