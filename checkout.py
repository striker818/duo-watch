#!/usr/bin/env python3
"""Drives Apple's checkout in Chrome as far as it can, then hands over to you. duo_watch.py starts it on a hit.

  checkout.py <buy url> [store number] [store name]   pre-fill, Add to Bag, Check Out, Pickup at the store,
                                                      earliest time, contact, Apple Card - stops at Review
  checkout.py --no-bag <buy url>                       pre-fill only (used by duo_watch.py --test-alert)
  checkout.py --test                                   dry run with a 20W adapter; also stops at Review
  checkout.py --test-phone                             dry run with an iPhone 18 Pro on Apple Card + T-Mobile, the
                                                      same steps as the Duo; stops at Review

Whenever a step needs you (T-Mobile PIN and picture code, Apple sign-in, card or carrier details, a page it doesn't know) it alerts you on the Mac
and phone, waits, and carries on once you've done it. It never places the order: Place Your Order is always yours.
Needs Chrome > View > Developer > Allow JavaScript from Apple Events.
"""
import json, os, subprocess, sys, time, urllib.request
from pathlib import Path

import duo_watch as w

HERE = Path(__file__).parent
LIMIT = 20 * 60   # give up after 20 minutes
TICK = 0.4
STUCK = 40        # same non-WAIT status this many ticks in a row (~25s with osascript overhead) -> ask for help

# Allow JavaScript from Apple Events is per Chrome profile, so open in a window whose profile allows it
OPEN_TAB = '''on run argv
  tell application "Google Chrome"
    activate
    set target to missing value
    repeat with w in windows
      try
        execute active tab of w javascript "1"
        set target to contents of w
        exit repeat
      end try
    end repeat
    if target is missing value then
      if (count of windows) = 0 then make new window
      set target to front window
    end if
    set t to make new tab at end of tabs of target with properties {URL:item 1 of argv}
    return id of t
  end tell
end run'''

# finds our tab by id; doesn't scan URLs, so it stays fast with lots of tabs open. "tab id N of w" alone is a lazy
# reference that "works" for any window (and then runs in that window's profile), so check the window really has it
RUN_JS = '''on run argv
  set tid to (item 1 of argv) as text   -- this Chrome reports tab ids as text
  tell application "Google Chrome"
    set t to missing value
    repeat with w in windows
      set ids to id of tabs of w   -- ids are text in this Chrome; "tab id N" lookups fail on them, so go by index
      repeat with i from 1 to count of ids
        if (item i of ids as text) is tid then set t to tab i of w
      end repeat
      if t is not missing value then exit repeat
    end repeat
    if t is missing value then return "__notab__"
    if loading of t then return "__loading__"
    set r to execute t javascript (item 2 of argv)
    if r is missing value then return ""
    return r as text
  end tell
end run'''

FRONT = '''on run argv
  set tid to (item 1 of argv) as text   -- this Chrome reports tab ids as text
  tell application "Google Chrome"
    activate
    repeat with w in windows
      set i to 0
      repeat with t in tabs of w
        set i to i + 1
        if (id of t as text) is tid then
          set active tab index of w to i
          set index of w to 1
          return
        end if
      end repeat
    end repeat
  end tell
end run'''

NOTIFY = 'on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv) sound name (item 3 of argv)\nend run'


def osa(script, *args, timeout=15):
    r = subprocess.run(["osascript", "-e", script, *map(str, args)], capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError(r.stderr.strip())
    return r.stdout.strip()


def js(tab, code):
    try:
        return osa(RUN_JS, tab, code)
    except subprocess.TimeoutExpired:
        return "__loading__"
    except RuntimeError as e:
        return "__error__ " + str(e)


FIND_TAB = '''on run argv
  tell application "Google Chrome"
    repeat with w in windows
      set urls to URL of tabs of w   -- one call per window, then search the list locally
      repeat with i from 1 to count of urls
        if item i of urls contains (item 1 of argv) then return (id of tab i of w) as text
      end repeat
    end repeat
  end tell
  return ""
end run'''


def open_tab(url):
    """Open url in the Chrome profile named by DUO_CHROME_PROFILE (e.g. "Profile 11"): each profile has its own Apple
    sign-in and bag, so checkout must always land in the same one. Without it, use the first window that allows JS."""
    profile = os.environ.get("DUO_CHROME_PROFILE", "")
    if not profile:
        return osa(OPEN_TAB, url)
    marker = f"duo-{os.getpid()}-{int(time.time())}"   # Apple ignores the #fragment; it lets us find the new tab
    subprocess.run(["open", "-na", "Google Chrome", "--args", f"--profile-directory={profile}", f"{url}#{marker}"], check=True)
    for _ in range(40):
        try:
            tab = osa(FIND_TAB, marker)
        except RuntimeError:   # "Connection is invalid" while the helper Chrome that open -n starts hands over and quits
            tab = ""
        if tab:
            osa(FRONT, tab)
            return tab
        time.sleep(0.25)
    raise RuntimeError(f"Chrome never opened the tab in {profile}")


def alert(tab, status, test):
    done = status.startswith("DONE")
    msg = status.split(" ", 1)[1]
    title = ("Duo: ready to place order" if done else "Duo checkout needs you") + (" [test]" if test else "")
    try:
        osa(FRONT, tab)
        osa(NOTIFY, title, msg, "Hero" if done else "Glass")
    except Exception as e:
        w.log(f"checkout: Mac alert failed: {e}")
    if w.NTFY_TOPIC:
        try:
            urllib.request.urlopen(urllib.request.Request(
                f"https://ntfy.sh/{w.NTFY_TOPIC}", data=f"On your Mac: {msg}".encode(),
                headers={"Title": title, "Priority": "default" if test else "urgent", "Tags": "computer"}), timeout=10)
        except Exception as e:
            w.log(f"checkout: ntfy failed: {e}")


def drive(url, store="", store_name="", add_to_bag=True, test=False):
    step_js = f"var DUO = {json.dumps({'store': store, 'storeName': store_name, 'zip': w.ZIP, 'phone': os.environ.get('DUO_TMOBILE_NUMBER', '')})};\n" + (HERE / "checkout.js").read_text()
    prefill_js = ("" if add_to_bag else "window.__duoNoBag = true;\n") + (HERE / "prefill.js").read_text()
    tab = open_tab(url)
    w.log(f"checkout: driving tab {tab} for {store_name or url}")
    last_raw, same, logged, told, adding, carrier_runs = None, 0, None, None, None, 0
    end = time.time() + LIMIT
    while time.time() < end:
        s = raw = js(tab, step_js)
        if s == "__notab__":
            return w.log("checkout: tab was closed - stopping")
        if s == "__loading__":
            time.sleep(TICK); continue
        if s.startswith("__error__"):
            if "Allow JavaScript from Apple Events" in s:
                s = "WAIT turn on Chrome > View > Developer > Allow JavaScript from Apple Events, then finish by hand"
                alert(tab, s, test); return w.log("checkout: " + s)
            w.log("checkout: " + s[:300]); time.sleep(1); continue
        if s == "NEED_PREFILL":
            js(tab, prefill_js); s = "prefill started"
        elif s.startswith("prefill: stopped"):
            s = "WAIT " + s[9:]
        elif s.startswith("prefill: ready") and not add_to_bag:
            s = "DONE choices are pre-filled (test - not added to bag)"
        elif s.startswith("prefill: continuing to T-Mobile"):
            carrier_runs += raw != last_raw
            if carrier_runs > 1:   # back on the buy page after the T-Mobile check and it wants it again: don't loop
                s = "WAIT Apple asked for the T-Mobile check again - take over from here"
        elif s.startswith("prefill: adding"):
            # Add to Bag was clicked; if Apple leaves us on the buy page, go to the bag ourselves
            adding = adding or time.time()
            if time.time() - adding > 6:
                js(tab, "location.href = 'https://www.apple.com/shop/bag'"); adding = None
        same = same + 1 if raw == last_raw else 0
        last_raw = raw
        if same == STUCK and not s.startswith(("WAIT", "DONE")):
            s = f"WAIT stuck at: {s} - take over from here"
        if s != logged:
            w.log("checkout: " + s); logged = s
        if s.startswith(("WAIT", "DONE")) and s != told:
            told = s
            alert(tab, s, test)
            if s.startswith("DONE"):
                return
        time.sleep(TICK)
    w.log("checkout: gave up after 20 min")


def preflight():
    """Return a problem that would stop checkout from working, or "" if Chrome is ready."""
    try:
        osa('''tell application "Google Chrome"
  if (count of windows) = 0 then return
  repeat with w in windows
    try
      execute active tab of w javascript "1"
      return
    end try
  end repeat
  execute active tab of front window javascript "1"
end tell''')   # fine as long as one window's profile allows it; checkout opens its tab there
        return ""
    except RuntimeError as e:
        if "Allow JavaScript from Apple Events" in str(e):
            return "Chrome blocks automation: turn on View > Developer > Allow JavaScript from Apple Events"
        return "" if "Invalid index" in str(e) or "-1728" in str(e) else f"Chrome check failed: {e}"   # no window open is fine
    except Exception as e:
        return f"Chrome check failed: {e}"


def test_store(part="MWVV3AM/A"):
    """Nearest store in DUO_US_STATE with the 20W adapter for pickup, for --test."""
    req = urllib.request.Request(w.URL.split("?")[0] + f"?parts.0={part}&location={w.ZIP}",
                                 headers={"User-Agent": "Mozilla/5.0 (Macintosh) Safari/605.1.15", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            stores = json.load(r)["body"].get("stores", [])
    except Exception as e:
        print(f"store lookup failed ({e}) - the dry run will ask you to pick the store")
        return "", ""
    s = next((s for s in stores if s.get("state") == w.US_STATE
              and s.get("partsAvailability", {}).get(part, {}).get("pickupDisplay") == "available"), {})
    return s.get("storeNumber", ""), s.get("storeName", "")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--preflight":
        print(preflight() or "Chrome is ready for checkout")
    elif a and a[0] == "--test-phone":
        store, name = test_store("MJQ44LL/A")   # iPhone 18 Pro 6.3" 256GB Silver, T-Mobile: same page flow as the Duo
        print(f"Dry run with an iPhone 18 Pro (Apple Card Monthly, T-Mobile), pickup at {name or '(no store found - it will ask you)'}. Stops at Review.")
        drive("https://www.apple.com/shop/buy-iphone/iphone-18-pro/6.3-inch-display-256gb-silver-t-mobile?purchaseOption=bfi&cppart=TMOBILE_IPHONE18PRO",
              store, name, test=True)
    elif a and a[0] == "--test":
        store, name = test_store()
        print(f"Dry run with a 20W adapter, pickup at {name or '(no store found - it will ask you)'}. Stops at Review.")
        drive("https://www.apple.com/shop/product/mwvv3am/a/20w-usb-c-power-adapter", store, name, test=True)
    elif a and a[0] == "--no-bag":
        drive(a[1], add_to_bag=False, test=True)
    elif a:
        drive(*a[:3])
    else:
        print(__doc__)
