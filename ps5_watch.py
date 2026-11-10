#!/usr/bin/env python3
"""PS5 Pro watcher for PlayStation Direct (direct.playstation.com) only.

Every 60 s it asks the same stock feed the product page itself calls (productList, ~5 KB JSON) whether the PS5 Pro
is in stock; every 3 min it also loads the product page (no redirects followed) to see whether PS Direct has turned
its queue-it waiting room on. On either it pushes an urgent ntfy alert whose link opens the product page in Safari,
where the phone userscript (ps5_phone_script.py) adds the Pro to the cart and stops before Place Order.

It only gets you to the page (or into the queue) fast. It never touches the queue, CAPTCHAs or bot checks.

  /usr/bin/python3 ps5_watch.py --loop      # what launchd runs (install_ps5.sh)
  /usr/bin/python3 ps5_watch.py             # one check, printed
  /usr/bin/python3 ps5_watch.py --test-alert          # push a test alert (the link opens the real Pro page)
  /usr/bin/python3 ps5_watch.py --test-checkout       # push a dry-run link: adds a $29 Vertical Stand instead,
                                                      # goes to Place Order, then takes the stand back out
  /usr/bin/python3 ps5_watch.py --history   # every stock window and queue seen so far
Settings in local.env (git ignores it): PS5_NTFY_TOPIC (default: DUO_NTFY_TOPIC, which the phone already follows).
"""
import json, os, random, re, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path
from urllib.parse import quote

PRO = "1000050805"                 # PlayStation 5 Pro Console 2TB (US), $899 as of 2026-11-10
STAND = "1000041162"               # Vertical Stand ($29, usually in stock, on the Pro page): the dry-run stand-in
PAGE = "https://direct.playstation.com/en-us/buy-consoles/playstation5-pro-console"
FEED = ("https://api.direct.playstation.com/commercewebservices/ps-direct-us/users/anonymous/products/productList"
        "?fields=BASIC&productCodes=" + PRO)
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
      "Version/18.0 Safari/605.1.15")
PERIOD = 60          # feed check; the page itself calls this feed on every load, so once a minute is light
PAGE_EVERY = 180     # queue check (the full ~220 KB page)
MAX_WAIT = 900       # error backoff cap

_local = Path(__file__).with_name("local.env")
if _local.exists():
    for _line in _local.read_text().splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _k, _v = _line.split("=", 1); os.environ.setdefault(_k.strip(), _v.strip())
TOPIC = os.environ.get("PS5_NTFY_TOPIC") or os.environ.get("DUO_NTFY_TOPIC", "")
HOME = Path.home()
LOG = HOME / "ps5_watch.log"
STATE = HOME / ".ps5_watch_state.json"     # {"stock": bool, "queue": bool, "since": t, "fails": n, ...}
HISTORY = HOME / "ps5_stock_history.csv"   # one row per stock or queue window, local time
FAILS = HOME / "ps5_check_failures.jsonl"
MAC = sys.platform == "darwin"


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json, text/html",
                                               "Origin": "https://direct.playstation.com",
                                               "Referer": PAGE})
    return urllib.request.urlopen(req, timeout=timeout)


def check_stock():
    """(in_stock, detail) from the feed. In stock = stockLevelStatus inStock/lowStock and purchasable."""
    with get(FEED) as r:
        p = json.load(r)["products"][0]
    status = (p.get("stock") or {}).get("stockLevelStatus", "?")
    price = (p.get("price") or {}).get("value")
    ok = status in ("inStock", "lowStock") and p.get("purchasable", False)
    return ok, f"{status}, ${price}, max {p.get('maxOrderQuantity')}/order"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def check_queue():
    """(queue_on, detail): the page redirects to queue-it once the waiting room is on, or its config says so."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(PAGE, headers={"User-Agent": UA, "Accept": "text/html"})
    try:
        with opener.open(req, timeout=20) as r:
            html = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            loc = e.headers.get("Location", "")
            return "queue-it" in loc.lower(), f"redirect {e.code} to {loc[:80]}"
        raise
    m = re.search(r'isQueueItEnabled\\?x22:(true|false)|"isQueueItEnabled"\s*:\s*(true|false)', html)
    flag = (m.group(1) or m.group(2)) if m else "?"
    return flag == "true", f"isQueueItEnabled={flag}"


def push(title, body, link=PAGE, priority="urgent", tags="video_game", topic=None):
    if not TOPIC:
        return log("no ntfy topic set (PS5_NTFY_TOPIC / DUO_NTFY_TOPIC)")
    try:
        with urllib.request.urlopen(urllib.request.Request(
                f"https://ntfy.sh/{topic or TOPIC}", data=body.encode(),
                headers={"Title": title, "Priority": priority, "Tags": tags,
                         # x-safari- opens Safari (not the PlayStation app), where the userscript runs
                         "Click": "x-safari-" + link,
                         "Actions": f"view, Open PS Direct, x-safari-{link}, clear=true"}), timeout=15) as r:
            log(f"ntfy sent ({title}): HTTP {r.status}")
    except Exception as e:
        log(f"ntfy failed: {e}")


def mac_notice(title, msg, sound="Glass"):
    if MAC:   # Notification Center banner: no window comes to the front
        subprocess.run(["osascript", "-e", f'on run argv\ndisplay notification (item 1 of argv) with title '
                        f'(item 2 of argv) sound name "{sound}"\nend run', msg, title])


def phone_link(code=PRO, test=False):
    """Product page plus ?ps5=<json> for the userscript: which product, and the time the alert was sent.
    A query, not a #hash: queue-it sends you back to the page's full URL after the line, and a hash doesn't survive."""
    cfg = {"code": code, "sent": int(time.time())}
    if test:
        cfg["test"] = True
    return PAGE + "?ps5=" + quote(json.dumps(cfg, separators=(",", ":")), safe="")


def record(kind, start, end):
    new = not HISTORY.exists()
    with HISTORY.open("a") as f:
        if new:
            f.write("kind,started,ended,minutes\n")
        f.write(f"{kind},{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start))},"
                f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end))},{(end - start) / 60:.1f}\n")


def load():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def failed(st, what, err):
    """Every failure to a file; one push after 5 in a row spanning 60+ s, at most once per 30 min."""
    with FAILS.open("a") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "what": what, "err": str(err)[:300]}) + "\n")
    st["fails"] = st.get("fails", 0) + 1
    st.setdefault("fail_since", time.time())
    log(f"{what} error ({st['fails']} in a row): {err}")
    if (st["fails"] >= 5 and time.time() - st["fail_since"] >= 60
            and time.time() - st.get("fail_pushed", 0) > 1800):
        st["fail_pushed"] = time.time()
        msg = f"PS Direct checks failing since {time.strftime('%-I:%M %p', time.localtime(st['fail_since']))}: {str(err)[:100]}"
        mac_notice("PS5 watcher can't check", msg, "Basso")
        push("PS5 watcher can't check", msg, priority="default", tags="warning")


def recovered(st):
    if st.get("fails", 0) >= 5 and st.get("fail_pushed"):
        span = f"{time.strftime('%-I:%M', time.localtime(st['fail_since']))}-{time.strftime('%-I:%M %p')}"
        push("PS5 watcher is checking again", f"PS Direct checks failed {span}. Back now.", priority="low", tags="white_check_mark")
    st.pop("fails", None); st.pop("fail_since", None); st.pop("fail_pushed", None)


def tick(st, do_page):
    now = time.time()
    try:
        ok, detail = check_stock()
    except Exception as e:
        failed(st, "stock", e); return False
    if ok and not st.get("stock"):
        st["stock"], st["stock_since"] = True, now
        log(f"IN STOCK: PS5 Pro ({detail})")
        mac_notice("PS5 Pro in stock on PS Direct!", detail)
        push("PS5 Pro IN STOCK on PS Direct", f"{detail}\nTap: Safari opens the Pro page and the script adds it to "
             "your cart and goes to Place Order. Sign in to Sony if asked; you tap Place Order.", phone_link())
    elif not ok and st.get("stock"):
        log(f"sold out again after {(now - st['stock_since']) / 60:.1f} min ({detail})")
        record("stock", st.pop("stock_since"), now); st["stock"] = False
    elif not ok:
        log(f"no stock ({detail})")
    if do_page:
        try:
            q, qd = check_queue()
        except Exception as e:
            failed(st, "page", e); return False
        if q and not st.get("queue"):
            st["queue"], st["queue_since"] = True, now
            log(f"QUEUE OPEN: {qd}")
            mac_notice("PS Direct queue is open", "Get in line on your phone now")
            push("PS Direct QUEUE OPEN - PS5 Pro", f"{qd}\nTap now to get in line in Safari. Once through, the "
                 "script adds the Pro to your cart. Don't close the tab.", phone_link())
        elif not q and st.get("queue"):
            log(f"queue closed after {(now - st['queue_since']) / 60:.1f} min ({qd})")
            record("queue", st.pop("queue_since"), now); st["queue"] = False
        elif not q:
            log(f"no queue ({qd})")
    recovered(st)
    return True


def loop():
    log(f"PS5 watcher started: feed every {PERIOD}s, page every {PAGE_EVERY}s, topic {'set' if TOPIC else 'MISSING'}")
    last_page, wait, last = 0, PERIOD, time.time()
    while True:
        st = load()
        if time.time() - last > 3 * max(wait, PERIOD):
            log(f"Mac was asleep {time.strftime('%-I:%M', time.localtime(last))}-{time.strftime('%-I:%M %p')} - no checks ran")
        last = time.time()
        do_page = time.time() - last_page >= PAGE_EVERY
        try:
            good = tick(st, do_page)
        except Exception as e:
            log(f"loop error: {e}"); good = False
        if do_page and good:
            last_page = time.time()
        STATE.write_text(json.dumps(st))
        # 3+ errors in a row double the wait (max 15 min); otherwise 60 s with a little jitter
        wait = PERIOD if st.get("fails", 0) < 3 else min(MAX_WAIT, PERIOD * 2 ** (st["fails"] - 2))
        time.sleep(wait + random.uniform(-3, 3))


def history():
    if not HISTORY.exists():
        return print("No stock or queue seen yet.")
    print(HISTORY.read_text())


if __name__ == "__main__":
    if "--test-alert" in sys.argv:
        push("TEST - PS5 Pro alert", "Test only. Tapping opens the PS5 Pro page in Safari without starting the "
             "checkout script. A real alert looks like this and starts it.", PAGE, priority="high")
    elif "--test-checkout" in sys.argv:
        push("TEST - PS Direct dry run", "Dry run: adds a $29 Vertical Stand (not the Pro), goes to Place Order and "
             "stops, then takes the stand back out after 20 s. Be signed in to Sony in Safari. Don't tap Place Order.",
             phone_link(STAND, test=True), priority="high")
    elif "--history" in sys.argv:
        history()
    elif "--loop" in sys.argv:
        loop()
    else:
        print("stock:", check_stock())
        print("queue:", check_queue())
