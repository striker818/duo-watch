#!/usr/bin/env python3
"""iPhone Duo stock agent - checks Apple Store pickup near you, alerts you, opens checkout.
Config: iPhone Duo (T-Mobile, no AppleCare, Apple Card Monthly Installments) Star White 256GB (MK1E4LL/A) + 512GB (MK1G4LL/A), pickup near DUO_ZIP.
"""
import json, os, smtplib, subprocess, sys, time, urllib.request
from email.message import EmailMessage
from pathlib import Path

BASE = "https://www.apple.com/shop/buy-iphone/iphone-duo/7.6-inch-display-"
PARTS = {  # part number -> (label, buy page)
    "MK1E4LL/A": ("256GB Star White T-Mobile", BASE + "256gb-star-white-t-mobile"),
    "MK1G4LL/A": ("512GB Star White T-Mobile", BASE + "512gb-star-white-t-mobile"),
}
# personal settings (ntfy topic, email, gmail app password) live in local.env next to this file, which git ignores
_local = Path(__file__).with_name("local.env")
if _local.exists():
    for _line in _local.read_text().splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _k, _v = _line.split("=", 1); os.environ.setdefault(_k.strip(), _v.strip())
ZIP = os.environ["DUO_ZIP"]                              # set in local.env or the GitHub secret
MAX_MILES = float(os.environ.get("DUO_MAX_MILES", "30"))
NTFY_TOPIC = os.environ.get("DUO_NTFY_TOPIC", "")        # push via ntfy app
GMAIL_USER = os.environ.get("DUO_GMAIL_USER", "")        # sender gmail
GMAIL_APP_PW = os.environ.get("DUO_GMAIL_APP_PW", "")    # gmail app password
EMAIL_TO = os.environ.get("DUO_EMAIL_TO", "")
STATE = Path(os.environ.get("DUO_STATE", Path.home() / ".duo_watch_state.json"))
LOG = Path(os.environ.get("DUO_LOG", Path.home() / "duo_watch.log"))
MAC = sys.platform == "darwin"                           # False on the GitHub Actions runner

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
            if p.get("pickupDisplay") == "available" and dist <= MAX_MILES:
                hits.append((label, url, f'{label} @ {s.get("storeName")} ({s.get("city")}, {dist:.0f} mi) - {p.get("pickupSearchQuote", "")}'))
    return hits, len(stores)

def notify(hits):
    urls = list(dict.fromkeys(u for _, u, _ in hits))
    BUY_URL = urls[0]
    body = ("iPhone Duo IN STOCK for pickup:\n" + "\n".join(t for *_, t in hits)
            + "\n\nCheckout: pick T-Mobile, NO AppleCare, Apple Card Monthly Installments, then Pickup.\n"
            + "Buy now:\n" + "\n".join(urls))
    if MAC:
        # Mac popup + sound
        subprocess.run(["osascript", "-e", f'display notification "{hits[0][2]}" with title "iPhone Duo in stock!" sound name "Glass"'])
        # open checkout page(s) in Chrome so they're ready to tap
        for u in urls:
            subprocess.run(["open", "-a", "Google Chrome", u])
    if NTFY_TOPIC:
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    f"https://ntfy.sh/{NTFY_TOPIC}", data=body.encode(),
                    headers={"Title": "iPhone Duo in stock!" + ("" if MAC else " [cloud]"), "Priority": "urgent", "Click": BUY_URL}), timeout=15) as r:
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

def main():
    try:
        hits, n = check()
    except Exception as e:
        log(f"check error: {e}"); return
    prev = json.loads(STATE.read_text()) if STATE.exists() else []
    if hits and [h[2] for h in hits] != prev:
        log("IN STOCK: " + " | ".join(h[2] for h in hits)); notify(hits)
    elif not hits:
        log(f"no stock ({n} stores checked)")
    STATE.write_text(json.dumps([h[2] for h in hits]))

if __name__ == "__main__":
    if "--test-alert" in sys.argv:
        lbl, url = PARTS["MK1G4LL/A"]; notify([(lbl, url, f"TEST - {lbl} @ Rosedale (Roseville, 5 mi)")]); sys.exit()
    main()
