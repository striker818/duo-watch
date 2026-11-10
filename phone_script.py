#!/usr/bin/env python3
"""Builds the iPhone version of the checkout: a userscript for the free Userscripts Safari extension (App Store).

It runs the same checkout.js the Mac uses, inside Safari on the phone. It only acts for 20 minutes after you open a
Duo alert link (apple.com/shop/bag#duo=...), which says which store has stock and which bag item to take out. From
there: remove the other size, Check Out, (you: Face ID), store + earliest time, pickup contact, terms, then it scrolls
to Place Your Order and rings it. It never taps Place Your Order.

The file is written to iCloud Drive/Userscripts, so it appears on the phone; set that folder in the Userscripts app.
Your ZIP and pickup person go into that file (from local.env), never into the alert link or this repo.

  /usr/bin/python3 phone_script.py          # (re)build after checkout.js or local.env changes
  /usr/bin/python3 phone_script.py --phone2 # the second phone's copy (its own Apple Account), see PHONE2 below
"""
import json, os
from pathlib import Path

import time
import duo_watch as w   # loads local.env

HERE = Path(__file__).parent
OUT = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Userscripts/duo-checkout.user.js"
LIFETIME_MIN = 20

TEMPLATE = """// ==UserScript==
// @name         __NAME__
// @description  From a Duo alert link: remove the other size, check out, pick the store, stop at Place Your Order.
// @match        https://www.apple.com/shop/*
// @match        https://*.store.apple.com/*
// @match        https://idmsa.apple.com/*
// @grant        GM.getValue
// @grant        GM.setValue
// @grant        GM.xmlHttpRequest
// @connect      ntfy.sh
// @run-at       document-end
// ==/UserScript==
// Built by duo-agent/phone_script.py - edit checkout.js there and rebuild, not this file.
(async () => {
  const BASE = __BASE__;
  const LOG_TOPIC = __LOG__;
  const MAC_TOPIC = __MACLOG__;   // null on phone 2: its own Apple Account and bag, so it never waits for the Mac
  // the alert link carries #duo=<json>: which store, which bag item to drop. Remember it across apple.com pages
  // (they're different sites, so page storage won't carry over; the extension's storage does).
  let cfg = null;
  const m = location.hash.match(/__KEY__=([^&]+)/);
  if (m) {
    try { cfg = JSON.parse(decodeURIComponent(m[1])); } catch (e) { cfg = null; }
    if (cfg) { cfg.t = Date.now(); window.name = "duo-" + cfg.t; await GM.setValue("duo", JSON.stringify(cfg)); }
    history.replaceState(null, "", location.pathname + location.search);
  } else {
    try { cfg = JSON.parse(await GM.getValue("duo", "null")); } catch (e) { cfg = null; }
  }
  if (!cfg || Date.now() - (cfg.restoreAt || cfg.t) > __LIFE__ * 60000) return;   // only right after an alert, never while you browse
  // Only the tab the alert opened acts. Tabs left open from a test or a failed run used to pick up the new alert too
  // and tap Check Out on the same bag (Apple 404s a second checkout of one bag). The alert's tab is tagged
  // window.name = "duo-<time the alert was opened>"; a tab tagged for an older alert stays out. Safari empties
  // window.name when the tab moves to another apple.com site (www > secure*.store > idmsa), so an empty name is
  // allowed and re-tagged (2026-11-05: requiring the tag stopped the script on every checkout page).
  const RUN = "duo-" + cfg.t;
  if (window.name && window.name !== RUN) return;
  window.name = RUN;
  var DUO = Object.assign({}, BASE, cfg);
  const save = () => GM.setValue("duo", JSON.stringify(cfg));
  DUO.rescues = { get: () => cfg.rescues || 0, set: n => { cfg.rescues = n; return save(); } };   // survives page loads
  DUO.qtyOne = { get: () => !!cfg.qtyOne, set: v => { cfg.qtyOne = v; return save(); } };   // store couldn't do 2: order 1
  // Is the Mac already past the bag? checkout.py posts "mac checkout" / "mac stopped" to its private log.
  const macPoll = () => GM.xmlHttpRequest({
    method: "GET", url: "https://ntfy.sh/" + MAC_TOPIC + "/json?poll=1&since=" + Math.floor((cfg.t - 120000) / 1000),
    onload: r => {
      const states = (r.responseText || "").split("\\n").filter(Boolean).map(l => { try { return JSON.parse(l).message; } catch (e) { return ""; } })
        .filter(m => /^mac (checkout|stopped)$/.test(m || ""));
      DUO.macBusy = states.length > 0 && states[states.length - 1] === "mac checkout";
    },
    onerror: () => { if (DUO.macBusy === undefined) DUO.macBusy = false; },   // can't tell: don't hold the phone up
    ontimeout: () => { if (DUO.macBusy === undefined) DUO.macBusy = false; }, timeout: 3000 });
  if (MAC_TOPIC) {
    macPoll(); setInterval(macPoll, 2000);
    setTimeout(() => { if (DUO.macBusy === undefined) DUO.macBusy = false; }, 3000);
  } else DUO.macBusy = false;
  const step = () => (
__STEP__
  );
  window.__duoPrefillRun = () => {
    window.__duoPrefill = "starting";
__PREFILL__
  };
  // progress reports to the Mac (a private ntfy topic only the Mac reads): status changes, plus a snapshot of the
  // page's controls if a step sits still for 8s. Field values are never sent, only whether they're filled.
  const report = msg => { try { GM.xmlHttpRequest({ method: "POST", url: "https://ntfy.sh/" + LOG_TOPIC, data: "[" + __BUILD__ + "] " + msg }); } catch (e) {} };   // build stamp: shows which copy the phone runs (iCloud can lag)
  const snapshot = () => {
    const seen = el => !!el && el.getClientRects().length > 0;
    const t = el => (el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 60);
    const btns = [...document.querySelectorAll("button, a[role=button]")].filter(seen).map(b => (b.disabled ? "[off]" : "") + (b.getAttribute("data-autom") || "") + ":" + t(b)).slice(0, 25);
    const radios = [...document.querySelectorAll("input[type=radio]")].map(r => r.name + "=" + r.value + (r.checked ? "*" : "") + (r.disabled ? "(off)" : "") + (seen(r) || (r.labels && r.labels[0] && seen(r.labels[0])) ? "" : "(hidden)")).slice(0, 25);
    const fields = [...document.querySelectorAll("input:not([type=radio]):not([type=hidden]), select")].filter(seen).map(f => (f.name || f.id) + (f.value ? "=filled" : "=EMPTY") + (f.required ? "!" : "")).slice(0, 25);
    const errs = [...document.querySelectorAll("[role=alert], [class*=error]")].filter(seen).map(t).filter(Boolean).slice(0, 5);
    return JSON.stringify({ path: location.pathname + location.search.slice(0, 80), w: innerWidth, btns, radios, fields, errs });
  };
  // while the Mac has the checkout: one tap moves it here (the Mac stops when it sees "takeover")
  const takeoverButton = show => {
    let b = document.getElementById("duo-takeover");
    if (!show) { if (b) b.remove(); return; }
    if (b) return;
    b = document.createElement("button"); b.id = "duo-takeover"; b.textContent = "Check out on this phone";
    b.style.cssText = "position:fixed;left:16px;right:16px;bottom:24px;z-index:2147483647;padding:16px;font:600 18px -apple-system;color:#fff;background:#0071e3;border:0;border-radius:14px";
    b.onclick = async () => {
      cfg.takeover = true; DUO.takeover = true; cfg.rescues = 0; await save();
      report("takeover"); location.href = "https://www.apple.com/shop/bag";
    };
    document.body.appendChild(b);
  };
  // After a run fails (sold out by the time checkout gets there), put the ready cart back for the next drop: the run
  // took the other size out of the bag. Bag > buy page of each missing size (prefill + Add to Bag) > bag > stop.
  const banner = (msg, color) => {
    let b = document.getElementById("duo-banner");
    if (!b) { b = document.createElement("div"); b.id = "duo-banner"; document.body.appendChild(b); }
    b.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:2147483647;padding:12px;font:600 16px -apple-system;text-align:center;color:#fff;pointer-events:none;background:" + (color || "#0071e3");
    b.textContent = "Duo: " + msg; return msg;
  };
  let lastGo = 0;
  const go = async url => { if (Date.now() - lastGo < 6000) return; lastGo = Date.now(); cfg.restoreTries = (cfg.restoreTries || 0) + 1; await save(); location.href = url; };
  // a bag line at quantity 2+ (a double Add to Bag) would order 2: put it back to 1. Returns true while fixing one.
  const fixQty = () => {
    const q = [...document.querySelectorAll("select")].find(x => /itemQuantity/.test(x.name || x.id) && +x.value > 1);
    if (!q) return false;
    if (Date.now() - (window.__duoQtyAt || 0) > 4000) {
      window.__duoQtyAt = Date.now();
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(q, "1");
      q.dispatchEvent(new Event("input", { bubbles: true })); q.dispatchEvent(new Event("change", { bubbles: true }));
    }
    return true;
  };
  const restoreStep = () => {
    if (/\/shop\/bag/.test(location.pathname)) {
      // the bag draws its items over a moment; reading it early misses some and adds them twice (2026-11-10)
      const nav = performance.getEntriesByType("navigation")[0];
      const loadedFor = nav && nav.loadEventEnd > 0 ? performance.now() - nav.loadEventEnd : document.readyState === "complete" ? 9e9 : 0;
      if (loadedFor < 2000) return banner("setting the ready cart back up: waiting for the bag to load...");
      if (fixQty()) return banner("setting the ready cart back up: putting a doubled phone back to quantity 1");
      // a bag item's name is the same for every carrier; its "Carrier:" line tells T-Mobile from unlocked
      const block = b => { let e = b; for (let i = 0; i < 10 && e.parentElement && !/Carrier:/.test(e.textContent); i++) e = e.parentElement; return e.textContent; };
      const fits = (b, r) => b.textContent.includes(r.name) && block(b).includes(r.carrier);
      const inBag = [...document.querySelectorAll("button[data-autom=bag-item-remove-button]")].filter(b => (DUO.readyCart || []).some(r => fits(b, r))).map(b => b.textContent);
      if (!document.querySelector("button[data-autom=bag-item-remove-button]") && !/bag is empty/i.test(document.body.innerText)) return banner("setting the ready cart back up: reading the bag...");
      // after a dry run (cfg.test), the test phone comes out of the bag too; a real run never removes anything here
      // a dry run's test phone, or a Duo on the wrong carrier (left from before a FINANCING switch), comes out
      const stray = [...document.querySelectorAll("button[data-autom=bag-item-remove-button]")]
        .filter(b => !(DUO.readyCart || []).some(r => fits(b, r)) && (cfg.test || (DUO.readyCart || []).some(r => b.textContent.includes(r.name))));
      if (stray.length) {
        if (Date.now() - lastGo > 2500) { lastGo = Date.now(); stray[0].click(); }
        return banner("dry run over: taking " + stray[0].textContent.replace(/^\s*Remove\s*/, "").trim() + " out of the bag");
      }
      const missing = (DUO.readyCart || []).filter(r => !inBag.some(t => t.includes(r.name)));
      if (!missing.length) return banner("DONE ready cart is back in the bag for the next drop", "#248a3d");
      if ((cfg.restoreTries || 0) >= 6) return banner("DONE couldn't put " + missing.map(r => r.name).join(" + ") + " back in the bag - add it by hand", "#d70015");
      go(missing[0].url);
      return banner("setting the ready cart back up: adding " + missing[0].name);
    }
    if (/\/shop\/buy-iphone/.test(location.pathname)) return step();   // prefill, Add to Bag, Review Bag
    go("https://www.apple.com/shop/bag");
    return banner("setting the ready cart back up: going to the bag");
  };
  let lastS = "", since = Date.now(), snapped = false, lastCheck = 0;
  const loop = setInterval(async () => {
    // a newer alert opened in another tab (or this run finished elsewhere): this tab stops for good
    if (Date.now() - lastCheck > 1000) {
      lastCheck = Date.now();
      let now = null;
      try { now = JSON.parse(await GM.getValue("duo", "null")); } catch (e) {}
      if (!now || now.t !== cfg.t) {
        clearInterval(loop); takeoverButton(false);
        const b = document.getElementById("duo-banner");
        if (b) { b.style.background = "#6e6e73"; b.textContent = "Duo checkout: stopped - a newer one started in another tab. You can close this tab."; }
        return report("status " + location.hostname + location.pathname + " | stopped: newer alert opened in another tab");
      }
    }
    let s;
    try { s = cfg.restore ? restoreStep() : step(); } catch (e) { s = "script error: " + e.message; }
    // the drop is over by the time checkout got there: after 8s (time to see it) set the ready cart back up
    if (!cfg.restore && s === lastS && /sold out and no other store/.test(s) && Date.now() - since > 8000 && (DUO.readyCart || []).length) {
      cfg.restore = true; cfg.restoreTries = 0; cfg.restoreAt = Date.now(); await save();   // fresh 20 min for the restore
      return report("status " + location.hostname + location.pathname + " | run failed - setting the ready cart back up");
    }
    takeoverButton(typeof s === "string" && s.startsWith("WAIT the Mac"));
    if (s !== lastS) {
      lastS = s; since = Date.now(); snapped = false;
      report("status " + location.hostname + location.pathname + " | " + s);
      if (/ again/.test(s)) report("again " + snapshot());   // had to click Continue twice: show me the page
    }
    else if (!snapped && Date.now() - since > 8000) { snapped = true; report("stuck " + snapshot()); }
    if (s === "NEED_PREFILL") window.__duoPrefillRun();
    // dry run reached the end: leave the final page up for 15s, then put the ready cart back
    if (cfg.test && !cfg.restore && typeof s === "string" && s.startsWith("DONE")) {
      if (s !== lastS) { lastS = s; since = Date.now(); report("status " + location.hostname + location.pathname + " | " + s); }
      if (Date.now() - since < 15000) return;
      cfg.restore = true; cfg.restoreTries = 0; cfg.restoreAt = Date.now(); await save();
      return report("status " + location.hostname + location.pathname + " | dry run done - setting the ready cart back up");
    }
    if (typeof s === "string" && s.startsWith("DONE")) {
      clearInterval(loop);
      await GM.setValue("duo", "null");   // finished: stop acting until the next alert
    }
  }, 150);
})();
"""


# PHONE2: a second iPhone on a different Apple Account (Apple allows 2 Duos per customer, so a second account means
# more phones). It is kept fully apart from the Mac and phone 1: its own alert topic (<topic>-p2, built by
# duo_watch.notify), its own link key (#duo2=, which phone 1's script ignores and vice versa), its own log topic
# (<topic>-phone2log, which the Mac never reads, so it can't trigger the Mac/phone-1 handover), no waiting for the Mac,
# and its own pickup person (DUO2_PICKUP_*, empty = whoever owns that account) and ready cart (DUO2_READY_CART).
# Its file goes to iCloud Drive/Userscripts-phone2: share that folder with phone 2's Apple Account and point phone 2's
# Userscripts app at it. Never put it in phone 1's Userscripts folder: both scripts would then run in one Safari.
OUT2 = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Userscripts-phone2/duo-checkout-phone2.user.js"


def build(phone2=False):
    pre, cart = ("DUO2_", w.P2_READY_CART) if phone2 else ("DUO_", w.READY_CART)
    base = {"device": "phone", "zip": w.ZIP, "phone": os.environ.get(pre + "TMOBILE_NUMBER", ""), "financing": w.FINANCING, "qty": int(os.environ.get(pre + "QTY", "1") or 1),
            "pickup": {k: os.environ.get(pre + "PICKUP_" + k.upper(), "") for k in ("first", "last", "email", "phone")},
            # sizes to keep in the bag between drops, as the bag names them, and their buy pages
            "readyCart": [{"name": "iPhone Duo " + w.PARTS[p][0].replace(" Unlocked", ""), "url": w.PARTS[p][1],
                           "carrier": "T-Mobile" if w.FINANCING else "any carrier"} for p in cart]}
    src = (TEMPLATE.replace("__BASE__", json.dumps(base)).replace("__LIFE__", str(LIFETIME_MIN)).replace("__BUILD__", json.dumps(("P2 " if phone2 else "") + time.strftime("%m-%d %H:%M")))
           .replace("__LOG__", json.dumps(w.NTFY_TOPIC + ("-phone2log" if phone2 else "-phonelog")))
           .replace("__MACLOG__", "null" if phone2 else json.dumps(w.NTFY_TOPIC + "-maclog"))
           .replace("__NAME__", "Duo checkout (phone 2)" if phone2 else "Duo checkout")
           .replace("__KEY__", w.P2_KEY if phone2 else "duo")
           .replace("__STEP__", (HERE / "checkout.js").read_text().rstrip().rstrip(";"))
           .replace("__PREFILL__", (HERE / "prefill.js").read_text()))
    out = OUT2 if phone2 else OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(src)
    return out


def link(store="", store_name="", drop_item="", buy_url=""):
    """Alert link for the phone: open the bag with what the userscript needs (no personal data in it)."""
    cfg = {"store": store, "storeName": store_name, "dropItem": drop_item, "buyUrl": buy_url}
    return "https://www.apple.com/shop/bag#duo=" + urllib_quote(json.dumps(cfg, separators=(",", ":")))


def urllib_quote(s):
    from urllib.parse import quote
    return quote(s, safe="")


if __name__ == "__main__":
    import sys
    print(f"wrote {build(phone2='--phone2' in sys.argv)}")
