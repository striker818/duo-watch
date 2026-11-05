#!/usr/bin/env python3
"""iPhone Duo stock agent - checks Apple Store pickup near you, alerts you, and on the Mac drives checkout
(checkout.py) up to the point it needs you.
Config: iPhone Duo (unlocked, paid in full, no AppleCare) Star White 256GB (MK1E4LL/A) + 512GB (MK1G4LL/A), pickup near DUO_ZIP.
"""
import json, os, smtplib, subprocess, sys, threading, time, urllib.request
from email.message import EmailMessage
from pathlib import Path

BASE = "https://www.apple.com/shop/buy-iphone/iphone-duo/7.6-inch-display-"
# these params make the page open with Buy (pay in full) and Connect to any carrier later (unlocked) already chosen
# (no trade-in is the default; AppleCare can't be preset from the URL). Until 2026-11-05 it was Apple Card Monthly +
# T-Mobile: "?purchaseOption=bfi&cppart=TMOBILE_IPHONEDUO" on the -t-mobile pages. Part numbers are the same either way.
PRESET = "?purchaseOption=fullPrice&cppart=UNLOCKED/US"
FINANCING = False   # True = Apple Card Monthly + T-Mobile (needs the old PRESET and -t-mobile pages); prefill.js and checkout.js follow it
PARTS = {  # part number -> (label, buy page)
    "MK1E4LL/A": ("256GB Star White Unlocked", BASE + "256gb-star-white-unlocked" + PRESET),
    "MK1G4LL/A": ("512GB Star White Unlocked", BASE + "512gb-star-white-unlocked" + PRESET),
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
OFFLINE = STATE.with_name(STATE.name + ".offline")   # {"since": t, "alerted": bool} while checks keep failing
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
        "Accept": "application/json", "Referer": BASE + "256gb-star-white-unlocked"})
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
# Ready cart: this part (e.g. MK1E4LL/A) sits in the Safari bag ahead of time, unlocked, paid in full, no AppleCare
# (Apple lets it in while pickup is sold out). When it's the one in stock, checkout starts at the bag and skips the buy
# page, the option picking and Add to Bag - the step Apple sometimes answers with a 404 at drop time.
READY_CART = [p.strip() for p in os.environ.get("DUO_READY_CART", "").split(",") if p.strip() in PARTS]  # one or both sizes
BAG_URL = "https://www.apple.com/shop/bag"
_checkout_lock = threading.Lock()   # the cloud listener and the Mac's own check can both start one

def start_checkout(hits, add_to_bag=True):
    with _checkout_lock:
        _start_checkout(hits, add_to_bag)

def part_of(h):
    return next(p for p, (l, _) in PARTS.items() if l == h[0])

def choose(hits):
    """The hit to go for: the ready cart's sizes first (fastest), then today's pickup, then 256GB before 512GB."""
    order = list(PARTS)
    return min(hits, key=lambda h: (part_of(h) not in READY_CART, "Today" not in h[2], order.index(part_of(h))))

def drop_items(part):
    """Ready-cart sizes to take out of the bag when `part` is the one in stock, as the bag names them."""
    return "|".join("iPhone Duo " + PARTS[p][0].replace(" Unlocked", "") for p in READY_CART if p != part)

def phone_link(h):
    """Phone alert link: with the ready cart, the bag (the phone userscript, phone_script.py, takes it from there);
    without it, the buy page as before."""
    if part_of(h) not in READY_CART:
        return h[1]
    from urllib.parse import quote
    cfg = {"store": h[3], "storeName": h[4], "dropItem": drop_items(part_of(h)), "buyUrl": h[1]}
    return BAG_URL + "#duo=" + quote(json.dumps(cfg, separators=(",", ":")), safe="")

def _start_checkout(hits, add_to_bag):
    """Start checkout.py in the background on one hit: today's pickup first, then 256GB before 512GB.
    Skips if a checkout from the last 20 minutes is still running, so the bag only ever gets one phone."""
    if CHECKOUT_PID.exists() and time.time() - CHECKOUT_PID.stat().st_mtime < 20 * 60:
        try:
            os.kill(int(CHECKOUT_PID.read_text()), 0)
            return log("checkout already running - not starting another")
        except (OSError, ValueError):
            pass
    label, url, _, store, name = h = choose(hits)
    env = dict(os.environ)
    if add_to_bag and READY_CART:
        if part_of(h) in READY_CART:
            env["DUO_BUY_URL"] = url; url = BAG_URL
        # the other ready-cart sizes come out of the bag, so only the in-stock one is ordered
        # ("iPhone Duo 256GB Star White", as the bag names it)
        if drop_items(part_of(h)):
            env["DUO_DROP_ITEM"] = drop_items(part_of(h))
    args = [url, store, name] if add_to_bag else ["--no-bag", url]
    proc = subprocess.Popen([sys.executable, str(Path(__file__).with_name("checkout.py")), *args], env=env,
                            stdout=subprocess.DEVNULL, stderr=open(Path.home() / "duo_checkout.err", "a"),
                            start_new_session=True)
    CHECKOUT_PID.write_text(str(proc.pid))
    log(f"checkout started for {label} @ {name} (pid {proc.pid})")

def notify(hits, add_to_bag=True):
    if MAC:  # first, every second counts: Chrome starts on the buy page while the alerts go out
        start_checkout(hits, add_to_bag)
    elif NTFY_TOPIC:  # cloud: tell the Mac right away so it starts checking out (see listen())
        try:
            urllib.request.urlopen(urllib.request.Request(
                f"https://ntfy.sh/{NTFY_TOPIC}-mac", data=json.dumps([[h[0], h[2], h[3], h[4]] for h in hits]).encode()), timeout=10)
        except Exception as e:
            log(f"Mac trigger failed: {e}")
    urls = list(dict.fromkeys(u for _, u, *_ in hits))
    BUY_URL = urls[0]
    body = ("iPhone Duo IN STOCK for pickup:\n" + "\n".join(h[2] for h in hits)
            + "\n\nCheckout: Buy (pay in full), Connect to any carrier later, NO AppleCare, then Pickup.\n"
            + "Buy now:\n" + "\n".join(urls))
    if MAC:
        # Mac popup + sound
        subprocess.run(["osascript", "-e", f'display notification "{hits[0][2]}" with title "iPhone Duo in stock!" sound name "Glass"'])
    if NTFY_TOPIC:
        # phone push: title says size + store, plus one button per in-stock size. Links use x-safari-https:// (iOS 17+)
        # so they open in Safari: faster than the Apple Store app, and Safari keeps the pay-in-full + unlocked presets
        first = hits[0][2].split(" (")[0].replace(" Star White Unlocked", "")       # "512GB @ Mall of America"
        best = choose(hits)
        phone_body = ("\n".join(h[2].split(" - ")[0] for h in hits)
                      + ("\nAt the Mac? It's checking out in Safari - sign in, then Place Your Order." if MAC else "")
                      + ("\nOn phone: tap to open your bag - it removes the other size and checks out; Face ID, then Place Your Order."
                         if part_of(best) in READY_CART else
                         "\nOn phone: opens Safari with Buy + unlocked set. Tap No AppleCare > Add to Bag > Pickup at that store"))
        # one button per in-stock size (best first); each opens the bag set up for that size and store
        firsts = {}
        for h in sorted(hits, key=lambda h: h is not best):
            firsts.setdefault(part_of(h), h)
        actions = "; ".join(f"view, Check out {h[0].split()[0]} @ {h[4]}, x-safari-{phone_link(h)}, clear=true"
                            for h in list(firsts.values())[:3])
        BUY_URL = phone_link(best)
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

def mac_notice(title, msg, sound="Basso"):
    subprocess.run(["osascript", "-e", f'on run argv\ndisplay notification (item 1 of argv) with title (item 2 of argv) sound name "{sound}"\nend run', msg, title])

def phone_notice(title, msg):
    if NTFY_TOPIC:
        try:
            urllib.request.urlopen(urllib.request.Request(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode(),
                                                          headers={"Title": title, "Tags": "warning"}), timeout=15)
        except Exception as e:
            log(f"ntfy failed: {e}")

def offline(failed, err=""):
    """Mac only: warn when checks keep failing (Wi-Fi/DNS down), since the watcher is blind then. The warning shows on
    the Mac right away; the phone hears about it once the Mac is back online (it can't send while offline)."""
    if not MAC:
        return
    st = json.loads(OFFLINE.read_text()) if OFFLINE.exists() else None
    if failed:
        st = st or {"since": time.time(), "alerted": False}
        if not st["alerted"] and time.time() - st["since"] >= 60:
            st["alerted"] = True
            log("offline for over a minute - alerting")
            mac_notice("Duo watcher is offline", f"Can't reach Apple since {time.strftime('%-I:%M %p', time.localtime(st['since']))}: {err[:80]}")
        OFFLINE.write_text(json.dumps(st))
    elif st:
        OFFLINE.unlink()
        if st["alerted"]:
            span = f"{time.strftime('%-I:%M', time.localtime(st['since']))}-{time.strftime('%-I:%M %p')}"
            log(f"back online (was offline {span})")
            phone_notice("Duo Mac watcher was offline", f"The Mac couldn't check from {span}. The cloud tracker kept checking. It's back now.")

def listen():
    """Mac: start checkout the moment the cloud tracker sees stock. The cloud posts its hits to the ntfy topic
    <DUO_NTFY_TOPIC>-mac (the phone isn't subscribed to it); this keeps a connection open to ntfy.sh, not Apple, so it
    adds no Apple requests. That halves how long a drop goes unnoticed and covers the Mac while Apple has it blocked."""
    labels = {lbl: url for lbl, url in PARTS.values()}
    while True:
        try:
            with urllib.request.urlopen(f"https://ntfy.sh/{NTFY_TOPIC}-mac/json", timeout=120) as r:  # keepalive every ~45s
                for line in r:
                    m = json.loads(line)
                    if m.get("event") != "message" or time.time() - m.get("time", 0) > 90:
                        continue
                    # only our own items: the buy link comes from PARTS, never from the message
                    hits = [(lbl, labels[lbl], text, store, name) for lbl, text, store, name in json.loads(m["message"])
                            if lbl in labels]
                    if hits:
                        log("cloud saw stock: " + " | ".join(h[2] for h in hits))
                        start_checkout(hits)
                        subprocess.run(["osascript", "-e", 'on run argv\ndisplay notification (item 1 of argv) with title "iPhone Duo in stock! (cloud)" sound name "Glass"\nend run', hits[0][2]])
        except Exception as e:
            log(f"cloud listener reconnecting: {e}")
            time.sleep(5)

def track(hits):
    """Record how long each size stays in stock at each store. Times are only as precise as the 60s polling."""
    now = time.time()
    current = {h[2].split(" (")[0] for h in hits}                 # "512GB Star White Unlocked @ Mall of America"
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
        log(f"check error: {e}"); offline(True, str(e)); return
    offline(False)
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
        if MAC and NTFY_TOPIC:
            threading.Thread(target=listen, daemon=True).start()
        last = time.time()
        while True:
            time.sleep((offset - time.time()) % PERIOD or PERIOD)
            if MAC and time.time() - last > 3 * PERIOD:  # the Mac slept (lid closed, power): nothing ran meanwhile
                span = f"{time.strftime('%-I:%M', time.localtime(last))}-{time.strftime('%-I:%M %p')}"
                log(f"Mac was asleep {span} - no checks ran")
                phone_notice("Duo Mac watcher was asleep", f"The Mac slept from {span} and didn't check. The cloud tracker kept checking. Keep the Mac awake and plugged in.")
            last = time.time()
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
