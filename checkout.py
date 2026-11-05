#!/usr/bin/env python3
"""Drives Apple's checkout in Safari or Chrome (DUO_BROWSER) as far as it can, then hands over to you. duo_watch.py starts it on a hit.

  checkout.py <buy url> [store number] [store name]   pre-fill, Add to Bag, Check Out, Pickup at the store,
                                                      earliest time, contact, Apple Card - stops at Review
  checkout.py --no-bag <buy url>                       pre-fill only (used by duo_watch.py --test-alert)
  checkout.py --test                                   dry run with a 20W adapter; also stops at Review
  checkout.py --test-phone                             dry run with any in-stock iPhone 18 Pro on Apple Card + T-Mobile, the
                                                      same steps as the Duo; stops at Review

Whenever a step needs you (T-Mobile PIN and picture code, Apple sign-in, card or carrier details, a page it doesn't know) it alerts you on the Mac
and phone, waits, and carries on once you've done it. It never places the order: Place Your Order is always yours.
Needs Allow JavaScript from Apple Events: Safari > Develop menu (turn on Settings > Advanced > Show features for web
developers first), or Chrome > View > Developer.
"""
import json, os, subprocess, sys, time, urllib.request
from pathlib import Path

import duo_watch as w

HERE = Path(__file__).parent
LIMIT = 20 * 60   # give up after 20 minutes
TICK = 0.25       # how often Python reads the status; the clicking itself happens in the page (see LOOP_MS)
LOOP_MS = 150     # in-page step interval: no osascript round trip per click
STUCK = 25        # seconds with the same non-WAIT status -> ask for help

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

# Safari: checkout gets its own window, so "current tab of window id N" always means our tab and the id never shifts
SAFARI = os.environ.get("DUO_BROWSER", "chrome").strip().lower() == "safari"
BROWSER = "Safari" if SAFARI else "Chrome"
SETTING = ("Safari > Develop > Allow JavaScript from Apple Events" if SAFARI
           else "Chrome > View > Developer > Allow JavaScript from Apple Events")

# the new window isn't always front right away (another window can be), so return the id that wasn't there before
SAFARI_OPEN = '''on run argv
  tell application "Finder" to set screenBox to bounds of window of desktop
  tell application "Safari"
    activate
    set oldIds to id of every window
    make new document with properties {URL:item 1 of argv}
    repeat 40 times
      set newIds to id of every window   -- fetch the list first; iterating "id of every window" directly fails
      repeat with i from 1 to count of newIds
        if oldIds does not contain (item i of newIds) then
          set bounds of window id (item i of newIds) to screenBox   -- fill the screen so you can see the whole page
          return (item i of newIds)
        end if
      end repeat
      delay 0.1
    end repeat
  end tell
  error "Safari never opened the checkout window"
end run'''

SAFARI_JS = '''on run argv
  tell application "Safari"
    try
      set t to current tab of window id ((item 1 of argv) as integer)
    on error
      return "__notab__"
    end try
    set state to do JavaScript "document.readyState" in t
    if state is missing value or state is "loading" then return "__loading__"
    try
      set r to do JavaScript (item 2 of argv) in t
      if r is missing value then return ""
      return r as text
    on error msg number n
      if n is -2753 then return ""   -- script returned nothing: Safari leaves r undefined
      error msg number n
    end try
  end tell
end run'''

SAFARI_FRONT = '''on run argv
  tell application "Safari"
    activate
    set index of window id ((item 1 of argv) as integer) to 1
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
        return osa(SAFARI_JS if SAFARI else RUN_JS, tab, code)
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


def front(tab):
    osa(SAFARI_FRONT if SAFARI else FRONT, tab)


def open_tab(url):
    """Safari: open url in a new window of its own. Chrome: open url in the Chrome profile named by DUO_CHROME_PROFILE (e.g. "Profile 11"): each profile has its own Apple
    sign-in and bag, so checkout must always land in the same one. Without it, use the first window that allows JS."""
    if SAFARI:
        return osa(SAFARI_OPEN, url)
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
            front(tab)
            return tab
        time.sleep(0.25)
    raise RuntimeError(f"Chrome never opened the tab in {profile}")


def alert(tab, status, test):
    done = status.startswith("DONE")
    msg = status.split(" ", 1)[1]
    title = ("Duo: ready to place order" if done else "Duo checkout needs you") + (" [test]" if test else "")
    try:
        front(tab)
        osa(NOTIFY, title, msg, "Hero" if done else "Glass")
        if done:  # the signal: a sound you can't miss plus a spoken cue, in the background so the loop isn't held up
            subprocess.Popen(["sh", "-c", "afplay /System/Library/Sounds/Hero.aiff; afplay /System/Library/Sounds/Hero.aiff; "
                              "say 'Ready. Tap Place Your Order.'"])
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
    args = {'store': store, 'storeName': store_name, 'zip': w.ZIP, 'phone': os.environ.get('DUO_TMOBILE_NUMBER', ''),
            'pickup': {k: os.environ.get('DUO_PICKUP_' + k.upper(), '') for k in ('first', 'last', 'email', 'phone')},
            # ready cart (see duo_watch.start_checkout): where to go if the bag turns out empty, and which bag item to
            # take out when a different size is the one in stock
            'buyUrl': os.environ.get('DUO_BUY_URL', ''), 'dropItem': os.environ.get('DUO_DROP_ITEM', '')}
    # Install checkout.js as a loop inside the page (re-installed after each page load, since navigation clears it).
    # Each Python tick then only reads window.__duoStatus, so steps follow each other in ~150ms, not ~600ms.
    step_src = (HERE / "checkout.js").read_text().rstrip().rstrip(";")
    prefill_src = (HERE / "prefill.js").read_text()
    boot_js = f"""var DUO = {json.dumps(args)};
if (!window.__duoLoop) {{
  window.__duoStep = () => (
{step_src}
  );
  window.__duoPrefillRun = () => {{
    window.__duoPrefill = "starting";   // set before prefill's first await, so it never starts twice
    {"" if add_to_bag else "window.__duoNoBag = true;"}
{prefill_src}
  }};
  window.__duoLoop = setInterval(() => {{
    let s;
    try {{ s = window.__duoStep(); }} catch (e) {{ s = "script error: " + e.message; }}
    if (s === "NEED_PREFILL") {{ window.__duoPrefillRun(); s = "prefill started"; }}
    window.__duoStatus = s;
  }}, {LOOP_MS});
}}
window.__duoStatus || "starting"
"""
    tab = open_tab(url)
    w.log(f"checkout: driving {BROWSER} {'window' if SAFARI else 'tab'} {tab} for {store_name or url}")
    last_raw, since, logged, told, adding, carrier_runs, flagged, adds = None, time.time(), None, None, None, 0, None, 0
    end = time.time() + LIMIT
    while time.time() < end:
        s = raw = js(tab, boot_js)
        if s == "__notab__":
            return w.log("checkout: tab was closed - stopping")
        if s == "__loading__":
            time.sleep(TICK); continue
        if s.startswith("__error__"):
            if "Allow JavaScript from Apple Events" in s:
                s = f"WAIT turn on {SETTING}, then finish by hand"
                alert(tab, s, test); return w.log("checkout: " + s)
            w.log("checkout: " + s[:300]); time.sleep(1); continue
        if s == "starting":
            time.sleep(TICK); continue
        if s.startswith("prefill: stopped"):
            s = "WAIT " + s[9:]
        elif s.startswith("prefill: ready") and not add_to_bag:
            s = "DONE choices are pre-filled (test - not added to bag)"
        elif s.startswith("prefill: continuing to T-Mobile"):
            carrier_runs += raw != last_raw
            if carrier_runs > 1:   # back on the buy page after the T-Mobile check and it wants it again: don't loop
                s = "WAIT Apple asked for the T-Mobile check again - take over from here"
        elif s.startswith("prefill: adding"):
            # Apple reloads the buy page instead of adding when the form wasn't ready; prefill then runs again.
            # Allow a couple of retries, then hand over rather than keep clicking Add to Bag
            adds += raw != last_raw
            if adds > 3:
                s = "WAIT Apple keeps bouncing Add to Bag back to the buy page - check the bag and take over"
            # Add to Bag was clicked; if Apple leaves us on the buy page, go to the bag ourselves
            adding = adding or time.time()
            if time.time() - adding > 6:
                js(tab, "location.href = 'https://www.apple.com/shop/bag'"); adding = None
        if raw != last_raw:
            since = time.time()
        last_raw = raw
        if time.time() - since > STUCK and flagged != raw and not s.startswith(("WAIT", "DONE")):
            flagged = raw
            s = f"WAIT stuck at: {s} - take over from here"
        if s != logged:
            w.log("checkout: " + s); logged = s
        if s.startswith(("WAIT", "DONE")) and s != told:
            told = s
            alert(tab, s, test)
            if s.startswith("DONE"):
                return
        time.sleep(TICK)
    w.log(f"checkout: gave up after {LIMIT // 60} min")


def preflight():
    """Return a problem that would stop checkout from working, or "" if the browser is ready."""
    if SAFARI:
        try:
            osa('''tell application "Safari"
  if (count of documents) = 0 then return
  do JavaScript "1" in front document
end tell''')
            return ""
        except RuntimeError as e:
            if "Allow JavaScript from Apple Events" in str(e):
                return f"Safari blocks automation: turn on {SETTING}"
            return f"Safari check failed: {e}"
        except Exception as e:
            return f"Safari check failed: {e}"
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


# iPhone 18 Pro part -> buy-page token; the part is the same for every carrier (the carrier goes in the link)
PRO_18 = {
    "MJQ34LL/A": "6.3-inch-display-256gb-black", "MJQ44LL/A": "6.3-inch-display-256gb-silver",
    "MJQ54LL/A": "6.3-inch-display-256gb-burgundy", "MJQ64LL/A": "6.3-inch-display-256gb-glacier",
    "MJQ74LL/A": "6.3-inch-display-512gb-black", "MJQ84LL/A": "6.3-inch-display-512gb-silver",
    "MJQ94LL/A": "6.3-inch-display-512gb-burgundy", "MJQA4LL/A": "6.3-inch-display-512gb-glacier",
    "MJQC4LL/A": "6.3-inch-display-1tb-black", "MJQD4LL/A": "6.3-inch-display-1tb-silver",
    "MJQE4LL/A": "6.3-inch-display-1tb-burgundy", "MJQF4LL/A": "6.3-inch-display-1tb-glacier",
    "MJQG4LL/A": "6.3-inch-display-2tb-black", "MJQH4LL/A": "6.3-inch-display-2tb-silver",
    "MJQJ4LL/A": "6.3-inch-display-2tb-burgundy", "MJQK4LL/A": "6.3-inch-display-2tb-glacier",
    "MJW44LL/A": "6.9-inch-display-256gb-black", "MJW54LL/A": "6.9-inch-display-256gb-silver",
    "MJW64LL/A": "6.9-inch-display-256gb-burgundy", "MJW74LL/A": "6.9-inch-display-256gb-glacier",
    "MJW84LL/A": "6.9-inch-display-512gb-black", "MJW94LL/A": "6.9-inch-display-512gb-silver",
    "MJWA4LL/A": "6.9-inch-display-512gb-burgundy", "MJWC4LL/A": "6.9-inch-display-512gb-glacier",
    "MJWD4LL/A": "6.9-inch-display-1tb-black", "MJWE4LL/A": "6.9-inch-display-1tb-silver",
    "MJWF4LL/A": "6.9-inch-display-1tb-burgundy", "MJWG4LL/A": "6.9-inch-display-1tb-glacier",
    "MJWH4LL/A": "6.9-inch-display-2tb-black", "MJWJ4LL/A": "6.9-inch-display-2tb-silver",
    "MJWK4LL/A": "6.9-inch-display-2tb-burgundy", "MJWL4LL/A": "6.9-inch-display-2tb-glacier",
}


def test_store(parts=("MWVV3AM/A",)):
    """First of `parts` (in order) with pickup at a store in DUO_US_STATE, nearest store first: (part, store, name).
    One request for all of them, so a dry run costs the watcher's rate limit as little as possible."""
    req = urllib.request.Request(w.URL.split("?")[0] + "?" + "&".join(f"parts.{i}={p}" for i, p in enumerate(parts))
                                 + f"&location={w.ZIP}",
                                 headers={"User-Agent": "Mozilla/5.0 (Macintosh) Safari/605.1.15", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            stores = json.load(r)["body"].get("stores", [])
    except Exception as e:
        print(f"store lookup failed ({e}) - the dry run will ask you to pick the store")
        return parts[0], "", ""
    for p in parts:
        for s in stores:
            if s.get("state") == w.US_STATE and s.get("partsAvailability", {}).get(p, {}).get("pickupDisplay") == "available":
                return p, s.get("storeNumber", ""), s.get("storeName", "")
    return parts[0], "", ""


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--preflight":
        print(preflight() or f"{BROWSER} is ready for checkout")
    elif a and a[0] == "--test-phone":
        # any iPhone 18 Pro with pickup nearby, on T-Mobile: same page flow as the Duo
        part, store, name = test_store(tuple(PRO_18))
        print(f"Dry run with an iPhone 18 Pro {PRO_18[part]} (Apple Card Monthly, T-Mobile), "
              f"pickup at {name or '(no store found - it will ask you)'}. Stops at Review.")
        drive(f"https://www.apple.com/shop/buy-iphone/iphone-18-pro/{PRO_18[part]}-t-mobile?purchaseOption=bfi&cppart=TMOBILE_IPHONE18PRO",
              store, name, test=True)
    elif a and a[0] == "--test":
        _, store, name = test_store()
        print(f"Dry run with a 20W adapter, pickup at {name or '(no store found - it will ask you)'}. Stops at Review.")
        drive("https://www.apple.com/shop/product/mwvv3am/a/20w-usb-c-power-adapter", store, name, test=True)
    elif a and a[0] == "--test-bag":
        # dry run of the ready-cart route: start at the bag (an in-stock 18 Pro already in it), pickup where it's in stock
        part, store, name = test_store(tuple(PRO_18))
        print(f"Dry run from the bag, pickup at {name or '(no store found - it will ask you)'}. Stops at Review.")
        drive("https://www.apple.com/shop/bag", store, name, test=True)
    elif a and a[0] == "--no-bag":
        drive(a[1], add_to_bag=False, test=True)
    elif a:
        drive(*a[:3])
    else:
        print(__doc__)
