#!/usr/bin/env python3
"""iPhone Duo stock agent - checks Apple Store pickup near you, alerts you, and on the Mac drives checkout
(checkout.py) up to the point it needs you.
Config: iPhone Duo (T-Mobile, no AppleCare, Apple Card Monthly Installments) Star White 256GB (MK1E4LL/A) + 512GB (MK1G4LL/A), pickup near DUO_ZIP.
"""
import json, os, smtplib, subprocess, sys, time, urllib.request
from email.message import EmailMessage
from pathlib import Path

BASE = "https://www.apple.com/shop/buy-iphone/iphone-duo/7.6-inch-display-"
# these params make the page open with Finance > Apple Card Monthly Installments and T-Mobile already chosen
# (no trade-in is the default; AppleCare can't be preset from the URL)
PRESET = "?purchaseOption=bfi&cppart=TMOBILE_IPHONEDUO"
PARTS = {  # part number -> (label, buy page)
    "MK1E4LL/A": ("256GB Star White T-Mobile", BASE + "256gb-star-white-t-mobile" + PRESET),
    "MK1G4LL/A": ("512GB Star White T-Mobile", BASE + "512gb-star-white-t-mobile" + PRESET),
}
# personal settings (ntfy topic, email, gmail app password) live in local.env next to this file, which git ignores
_local = Path(__file__).with_name("local.env")
if _local.exists():
    for _line in _local.read_text().splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _k, _v = _line.split("=", 1); os.environ.setdefault(_k.strip(), _v.strip())
ZIP = os.environ["DUO_ZIP"]                              # set in local.env or the GitHub secret
US_STATE = os.environ.get("DUO_US_STATE", "MN")              # any Apple Store in this state counts
NTFY_TOPIC = os.environ.get("DUO_NTFY_TOPIC", "")        # push via ntfy app
GMAIL_USER = os.environ.get("DUO_GMAIL_USER", "")        # sender gmail
GMAIL_APP_PW = os.environ.get("DUO_GMAIL_APP_PW", "")    # gmail app password
EMAIL_TO = os.environ.get("DUO_EMAIL_TO", "")
STATE = Path(os.environ.get("DUO_STATE", Path.home() / ".duo_watch_state.json"))
LOG = Path(os.environ.get("DUO_LOG", Path.home() / "duo_watch.log"))
HISTORY = Path(os.environ.get("DUO_HISTORY", Path.home() / "duo_stock_history.csv"))  # one row per stock window
OPEN = Path(os.environ.get("DUO_OPEN", Path.home() / ".duo_stock_open.json"))        # windows still in stock
BLOCKED = STATE.with_name(STATE.name + ".blocked")   # touched when Apple rate-limits us (HTTP 541)
BACKOFF = 600   # seconds to pause after a block; a test block (polling every 3s) lasted 25+ min and checking
                # during it may extend it
MAC = sys.platform == "darwin"                           # False on the GitHub Actions runner
PERIOD = 60     # seconds between checks per tracker (36s and 48s still got blocked every 1-2h); the Mac checks on clock
                # slot 0 and the cloud on slot 30, so together they check every 30s

# /shop/fulfillment-messages started returning HTTP 541 for all parts (Nov 2026); this one still works
URL = ("https://www.apple.com/shop/retail/pickup-message?"
       + "&".join(f"parts.{i}={p}" for i, p in enumerate(PARTS)) + f"&location={ZIP}")

def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line)
    with LOG.open("a") as f:
        f.write(line + "\n")

def check():
    req = urllib.request.Request(URL, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
        "Accept": "application/json", "Referer": BASE + "256gb-star-white-t-mobile"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    stores = data["body"].get("stores", [])
    hits = []
    for s in stores:
        dist = float(str(s.get("storedistance", 999)).split()[0] or 999)
        for part, (label, url) in PARTS.items():
            p = s.get("partsAvailability", {}).get(part, {})
            if p.get("pickupDisplay") == "available" and s.get("state") == US_STATE:
                hits.append((label, url, f'{label} @ {s.get("storeName")} ({s.get("city")}, {dist:.0f} mi) - {p.get("pickupSearchQuote", "")}',
                             s.get("storeNumber", ""), s.get("storeName", "")))
    return hits, len(stores)

CHECKOUT_PID = Path.home() / ".duo_checkout.pid"

def start_checkout(hits, add_to_bag=True):
    """Start checkout.py in the background on one hit: today's pickup first, then 256GB before 512GB.
    Skips if a checkout from the last 20 minutes is still running, so the bag only ever gets one phone."""
    if CHECKOUT_PID.exists() and time.time() - CHECKOUT_PID.stat().st_mtime < 20 * 60:
        try:
            os.kill(int(CHECKOUT_PID.read_text()), 0)
            return log("checkout already running - not starting another")
        except (OSError, ValueError):
            pass
    order = list(PARTS)
    label, url, _, store, name = min(hits, key=lambda h: ("Today" not in h[2], order.index(
        next(p for p, (l, _) in PARTS.items() if l == h[0]))))
    args = [url, store, name] if add_to_bag else ["--no-bag", url]
    proc = subprocess.Popen([sys.executable, str(Path(__file__).with_name("checkout.py")), *args],
                            stdout=subprocess.DEVNULL, stderr=open(Path.home() / "duo_checkout.err", "a"),
                            start_new_session=True)
    CHECKOUT_PID.write_text(str(proc.pid))
    log(f"checkout started for {label} @ {name} (pid {proc.pid})")

def notify(hits, add_to_bag=True):
    if MAC:  # first, every second counts: Chrome starts on the buy page while the alerts go out
        start_checkout(hits, add_to_bag)
    urls = list(dict.fromkeys(u for _, u, *_ in hits))
    BUY_URL = urls[0]
    body = ("iPhone Duo IN STOCK for pickup:\n" + "\n".join(h[2] for h in hits)
            + "\n\nCheckout: pick T-Mobile, NO AppleCare, Apple Card Monthly Installments, then Pickup.\n"
            + "Buy now:\n" + "\n".join(urls))
    if MAC:
        # Mac popup + sound
        subprocess.run(["osascript", "-e", f'display notification "{hits[0][2]}" with title "iPhone Duo in stock!" sound name "Glass"'])
    if NTFY_TOPIC:
        # phone push: title says size + store, plus one button per in-stock size. Links use x-safari-https:// (iOS 17+)
        # so they open in Safari: faster than the Apple Store app, and Safari keeps the Apple Card + T-Mobile presets
        first = hits[0][2].split(" (")[0].replace(" Star White T-Mobile", "")       # "512GB @ Mall of America"
        phone_body = ("\n".join(h[2].split(" - ")[0] for h in hits)
                      + ("\nAt the Mac? It's checking out in Chrome - sign in when asked, then Place Order." if MAC else "")
                      + "\nOn phone: opens Safari with Apple Card Monthly + T-Mobile set. Tap No AppleCare > Add to Bag > Pickup at that store")
        actions = "; ".join(f"view, Buy {lbl.split()[0]}, x-safari-{u}, clear=true"
                            for lbl, u in PARTS.values() if u in urls)
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    f"https://ntfy.sh/{NTFY_TOPIC}", data=phone_body.encode(),
                    headers={"Title": f"Duo in stock: {first}" + ("" if MAC else " [cloud]"), "Priority": "urgent",
                             "Tags": "rotating_light", "Click": "x-safari-" + BUY_URL, "Actions": actions}), timeout=15) as r:
                log(f"ntfy sent: HTTP {r.status}")
        except Exception as e:
            log(f"ntfy failed: {e}")
    if GMAIL_USER and GMAIL_APP_PW:
        try:
            m = EmailMessage(); m["Subject"] = "iPhone Duo in stock - go buy"
            m["From"] = GMAIL_USER; m["To"] = EMAIL_TO; m.set_content(body)
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
                s.login(GMAIL_USER, GMAIL_APP_PW); s.send_message(m)
        except Exception as e:
            log(f"email failed: {e}")

def track(hits):
    """Record how long each size stays in stock at each store. Times are only as precise as the 60s polling."""
    now = time.time()
    current = {h[2].split(" (")[0] for h in hits}                 # "512GB Star White T-Mobile @ Mall of America"
    opened = json.loads(OPEN.read_text()) if OPEN.exists() else {}
    for key in current - opened.keys():
        opened[key] = now
        log(f"stock window opened: {key}")
    for key in opened.keys() - current:
        start = opened.pop(key)
        new = not HISTORY.exists()
        with HISTORY.open("a") as f:
            if new:
                f.write("item,store,in_stock_at,sold_out_at,minutes\n")
            item, store = key.split(" @ ", 1)
            f.write(f'{item},{store},{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start))},'
                    f'{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))},{(now - start) / 60:.1f}\n')
        log(f"stock window closed: {key} after {(now - start) / 60:.1f} min")
    OPEN.write_text(json.dumps(opened))

def history():
    """Print every stock window seen so far, plus averages per size."""
    import csv
    rows = list(csv.DictReader(HISTORY.open())) if HISTORY.exists() else []
    opened = json.loads(OPEN.read_text()) if OPEN.exists() else {}
    if not rows and not opened:
        return print("No stock seen yet.")
    for r in rows:
        print(f'{r["in_stock_at"]}  {r["item"]:<28} {r["store"]:<18} sold out after {float(r["minutes"]):.1f} min')
    for key, start in opened.items():
        print(f'{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start))}  {key}  STILL IN STOCK ({(time.time() - start) / 60:.1f} min so far)')
    for item in sorted({r["item"] for r in rows}):
        m = [float(r["minutes"]) for r in rows if r["item"] == item]
        print(f"{item}: {len(m)} windows, average {sum(m) / len(m):.1f} min, shortest {min(m):.1f}, longest {max(m):.1f}")
    print("(times are within about 60 seconds, the polling interval)")

def main():
    if BLOCKED.exists() and time.time() - BLOCKED.stat().st_mtime < BACKOFF:
        return
    try:
        hits, n = check()
    except Exception as e:
        if getattr(e, "code", None) == 541:
            BLOCKED.touch(); log(f"blocked by Apple (HTTP 541) - pausing checks for {BACKOFF // 60} min"); return
        log(f"check error: {e}"); return
    track(hits)   # first, so a failing alert or checkout can't lose the drop record
    prev = json.loads(STATE.read_text()) if STATE.exists() else []
    if hits and [h[2] for h in hits] != prev:
        log("IN STOCK: " + " | ".join(h[2] for h in hits)); notify(hits)
    elif not hits:
        log(f"no stock ({n} stores checked)")
    STATE.write_text(json.dumps([h[2] for h in hits]))

if __name__ == "__main__":
    if "--test-alert" in sys.argv:
        lbl, url = PARTS["MK1G4LL/A"]; notify([(lbl, url, f"TEST - {lbl} @ Rosedale (Roseville, 5 mi)", "R022", "Rosedale")], add_to_bag=False); sys.exit()
    if "--history" in sys.argv:
        history(); sys.exit()
    if "--drops" in sys.argv:  # when drops happen, by hour and weekday (cloud + Mac records merged)
        subprocess.run([sys.executable, str(Path(__file__).with_name("drops.py"))]); sys.exit()
    if "--test-checkout" in sys.argv:  # dry run of the whole checkout with a 20W adapter, stops at Review
        subprocess.run([sys.executable, str(Path(__file__).with_name("checkout.py")), "--test"]); sys.exit()
    if "--loop" in sys.argv:  # --loop N: check whenever the clock is N seconds into each PERIOD-second slot
        offset = int(sys.argv[sys.argv.index("--loop") + 1])
        checked = 0
        while True:
            time.sleep((offset - time.time()) % PERIOD or PERIOD)
            if MAC and time.time() - checked > 3 * 3600:  # Chrome updates can switch Apple Events JS back off
                checked = time.time()
                try:
                    import checkout
                    problem = checkout.preflight()
                except Exception as e:
                    problem = f"Chrome check failed: {e}"
                if problem:
                    log("preflight: " + problem)
                    subprocess.run(["osascript", "-e", 'on run argv\ndisplay notification (item 1 of argv) with title "Duo watcher can\'t check out" sound name "Basso"\nend run', problem])
            try:
                main()
            except Exception as e:
                log(f"loop error: {e}")
    main()
