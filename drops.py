#!/usr/bin/env python3
"""When do iPhone Duos drop? Merges every stock sighting we have and shows them by weekday and hour (Central time).

Sources (whatever exists): the cloud tracker's data/stock_history.csv (fetched from GitHub, or a path given on the
command line), the Mac's ~/duo_stock_history.csv, and the IN STOCK lines in the Mac's ~/duo_watch.log. The same drop
seen by both trackers is counted once.

  /usr/bin/python3 drops.py                          # summary in the terminal
  /usr/bin/python3 drops.py --md data/stock_history.csv > data/DROPS.md   # markdown page (the cloud tracker does this)
"""
import csv, io, re, sys, urllib.request
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

CLOUD_CSV = "https://raw.githubusercontent.com/striker818/duo-watch/main/data/stock_history.csv"
MAC_CSV = Path.home() / "duo_stock_history.csv"
MAC_LOG = Path.home() / "duo_watch.log"
FMT = "%Y-%m-%d %H:%M:%S"
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def hour_label(h):
    return f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"


def from_csv(text, source):
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        try:
            out.append({"at": datetime.strptime(r["in_stock_at"], FMT), "item": r["item"], "store": r["store"],
                        "minutes": float(r["minutes"]), "source": source})
        except (KeyError, ValueError):
            pass
    return out


def from_log(path):
    # 2026-11-03 16:55:00 IN STOCK: 256GB Star White T-Mobile @ Southdale (Edina, 15 mi) - Available Today | ...
    out = []
    for line in path.read_text(errors="ignore").splitlines():
        m = re.match(r"(\S+ \S+) IN STOCK: (.*)", line)
        if not m or "TEST" in line:
            continue
        for hit in m.group(2).split(" | "):
            item, _, rest = hit.partition(" @ ")
            out.append({"at": datetime.strptime(m.group(1), FMT), "item": item.strip(),
                        "store": rest.split(" (")[0].strip(), "minutes": None, "source": "mac"})
    return out


def load(paths):
    events = []
    if paths:
        for p in paths:
            events += from_csv(Path(p).read_text(), "cloud")
        return events
    try:
        with urllib.request.urlopen(CLOUD_CSV, timeout=15) as r:
            events += from_csv(r.read().decode(), "cloud")
    except Exception as e:
        print(f"(couldn't fetch the cloud history: {e})", file=sys.stderr)
    if MAC_CSV.exists():
        events += from_csv(MAC_CSV.read_text(), "mac")
    if MAC_LOG.exists():
        events += from_log(MAC_LOG)
    return events


def merge(events):
    """One drop per item+store within 3 minutes; keep the earliest start and any known duration."""
    drops = []
    for e in sorted(events, key=lambda e: e["at"]):
        d = next((d for d in drops if d["item"] == e["item"] and d["store"] == e["store"]
                  and abs(e["at"] - d["at"]) <= timedelta(minutes=3)), None)
        if d:
            d["minutes"] = d["minutes"] if d["minutes"] is not None else e["minutes"]
            d["sources"].add(e["source"])
        else:
            drops.append({**e, "sources": {e["source"]}})
    return drops


def lasted(d):
    return "?" if d["minutes"] is None else f"{d['minutes']:.0f} min" if d["minutes"] >= 1 else "<1 min"


def summary(drops, md=False):
    L = []
    h = (lambda t: L.append(f"\n## {t}\n")) if md else (lambda t: L.append(f"\n{t}"))
    if md:
        L.append("# When iPhone Duos drop\n")
        L.append(f"All times Central. Updated {datetime.now().strftime('%a %b %-d, %-I:%M %p')}. "
                 "Each tracker checks once a minute, so times are within about a minute.\n")
    if not drops:
        L.append("No drops seen yet.")
        return "\n".join(L)

    by_hour = Counter(d["at"].hour for d in drops)
    by_day = Counter(d["at"].weekday() for d in drops)
    top = sorted(by_hour, key=lambda x: (-by_hour[x], x))[:3]
    mins = [d["minutes"] for d in drops if d["minutes"] is not None]
    h("Get ready around")
    L.append(("- " if md else "  ") + ", ".join(f"{hour_label(x)}-{hour_label((x + 1) % 24)} ({by_hour[x]})" for x in top))
    L.append(("- " if md else "  ") + f"{len(drops)} drop{'' if len(drops) == 1 else 's'} so far" + (f"; stock lasted {sum(mins) / len(mins):.0f} min on average"
                                                                    f" (shortest {min(mins):.0f}, longest {max(mins):.0f})" if mins else ""))
    if len(drops) < 10:
        L.append(("- " if md else "  ") + "Too few drops to see a real pattern yet. It gets more useful after 10 or more.")

    h("By hour")
    peak = max(by_hour.values())
    for x in range(24):
        if by_hour[x]:
            bar = "█" * round(by_hour[x] / peak * 20)
            L.append(f"{'- ' if md else '  '}{hour_label(x):>5}  {bar} {by_hour[x]}")
    h("By day")
    L.append(("- " if md else "  ") + "  ".join(f"{DAYS[i]} {by_day[i]}" for i in range(7)))

    h("Every drop (newest first)")
    if md:
        L.append("| When | Item | Store | Lasted |\n|---|---|---|---|")
    for d in sorted(drops, key=lambda d: d["at"], reverse=True):
        when = d["at"].strftime("%a %b %-d, %-I:%M %p")
        L.append(f"| {when} | {d['item']} | {d['store']} | {lasted(d)} |" if md
                 else f"  {when:<22} {d['item']:<28} {d['store']:<16} {lasted(d)}")
    return "\n".join(L)


if __name__ == "__main__":
    md = "--md" in sys.argv
    paths = [a for a in sys.argv[1:] if not a.startswith("--")]
    print(summary(merge(load(paths)), md))
