#!/usr/bin/env python3
"""Builds the PS5 Pro userscript for the Userscripts Safari extension on the phone (same setup as the Duo one).

It wraps ps5_checkout.js (the page logic) with a header and writes iCloud Drive/Userscripts/ps5-checkout.user.js.
It only matches direct.playstation.com, so it never runs alongside the Duo script on apple.com.
It acts only for LIFETIME_MIN after you tap a PS5 alert (ps5_watch.py), and stops at Place Order: you tap that.
Progress goes to the ntfy topic <topic>-ps5log (not -phonelog: the Duo Mac reads that one and would stop its own
checkout on a "/checkout" status). Each line starts with the build time, so you can tell an old iCloud copy.

  /usr/bin/python3 ps5_phone_script.py      # (re)build after editing ps5_checkout.js
"""
import json, time
from pathlib import Path

import ps5_watch as w   # loads local.env

HERE = Path(__file__).parent
OUT = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Userscripts/ps5-checkout.user.js"
LIFETIME_MIN = 60   # long enough to wait out a queue-it line

HEADER = """// ==UserScript==
// @name         PS5 Pro checkout (PS Direct)
// @description  From a PS5 alert: add the PS5 Pro to the cart on PS Direct and stop at Place Order. Never places it.
// @match        https://direct.playstation.com/*
// @grant        GM.getValue
// @grant        GM.setValue
// @grant        GM.xmlHttpRequest
// @connect      ntfy.sh
// @run-at       document-end
// ==/UserScript==
// Built by duo-agent/ps5_phone_script.py - edit ps5_checkout.js there and rebuild, not this file.
"""


def source():
    base = {"log": w.TOPIC + "-ps5log", "build": time.strftime("%m-%d %H:%M"), "life": LIFETIME_MIN,
            "page": w.PAGE, "stand": w.STAND,
            # as the cart names them
            "names": {w.PRO: "PlayStation®5 Pro Console", w.STAND: "Vertical Stand for PS5® Consoles"}}
    return HEADER + "const PS5_BASE = " + json.dumps(base, ensure_ascii=False) + ";\n" + (HERE / "ps5_checkout.js").read_text()


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(source())
    print(f"wrote {OUT}")
