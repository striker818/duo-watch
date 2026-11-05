#!/usr/bin/env python3
"""Builds the iPhone version of the checkout: a userscript for the free Userscripts Safari extension (App Store).

It runs the same checkout.js the Mac uses, inside Safari on the phone. It only acts for 20 minutes after you open a
Duo alert link (apple.com/shop/bag#duo=...), which says which store has stock and which bag item to take out. From
there: remove the other size, Check Out, (you: Face ID), store + earliest time, pickup contact, terms, then it scrolls
to Place Your Order and rings it. It never taps Place Your Order.

The file is written to iCloud Drive/Userscripts, so it appears on the phone; set that folder in the Userscripts app.
Your ZIP and pickup person go into that file (from local.env), never into the alert link or this repo.

  /usr/bin/python3 phone_script.py          # (re)build after checkout.js or local.env changes
"""
import json, os
from pathlib import Path

import duo_watch as w   # loads local.env

HERE = Path(__file__).parent
OUT = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Userscripts/duo-checkout.user.js"
LIFETIME_MIN = 20

TEMPLATE = """// ==UserScript==
// @name         Duo checkout
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
  const MAC_TOPIC = __MACLOG__;
  // the alert link carries #duo=<json>: which store, which bag item to drop. Remember it across apple.com pages
  // (they're different sites, so page storage won't carry over; the extension's storage does).
  let cfg = null;
  const m = location.hash.match(/duo=([^&]+)/);
  if (m) {
    try { cfg = JSON.parse(decodeURIComponent(m[1])); } catch (e) { cfg = null; }
    if (cfg) { cfg.t = Date.now(); await GM.setValue("duo", JSON.stringify(cfg)); }
    history.replaceState(null, "", location.pathname + location.search);
  } else {
    try { cfg = JSON.parse(await GM.getValue("duo", "null")); } catch (e) { cfg = null; }
  }
  if (!cfg || Date.now() - cfg.t > __LIFE__ * 60000) return;   // only right after an alert, never while you browse
  var DUO = Object.assign({}, BASE, cfg);
  const save = () => GM.setValue("duo", JSON.stringify(cfg));
  DUO.rescues = { get: () => cfg.rescues || 0, set: n => { cfg.rescues = n; return save(); } };   // survives page loads
  // Is the Mac already past the bag? checkout.py posts "mac checkout" / "mac stopped" to its private log.
  const macPoll = () => GM.xmlHttpRequest({
    method: "GET", url: "https://ntfy.sh/" + MAC_TOPIC + "/json?poll=1&since=" + Math.floor((cfg.t - 120000) / 1000),
    onload: r => {
      const states = (r.responseText || "").split("\\n").filter(Boolean).map(l => { try { return JSON.parse(l).message; } catch (e) { return ""; } })
        .filter(m => /^mac (checkout|stopped)$/.test(m || ""));
      DUO.macBusy = states.length > 0 && states[states.length - 1] === "mac checkout";
    } });
  macPoll(); setInterval(macPoll, 2000);
  const step = () => (
__STEP__
  );
  window.__duoPrefillRun = () => {
    window.__duoPrefill = "starting";
__PREFILL__
  };
  // progress reports to the Mac (a private ntfy topic only the Mac reads): status changes, plus a snapshot of the
  // page's controls if a step sits still for 8s. Field values are never sent, only whether they're filled.
  const report = msg => { try { GM.xmlHttpRequest({ method: "POST", url: "https://ntfy.sh/" + LOG_TOPIC, data: msg }); } catch (e) {} };
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
  let lastS = "", since = Date.now(), snapped = false;
  const loop = setInterval(async () => {
    let s;
    try { s = step(); } catch (e) { s = "script error: " + e.message; }
    takeoverButton(typeof s === "string" && s.startsWith("WAIT the Mac"));
    if (s !== lastS) {
      lastS = s; since = Date.now(); snapped = false;
      report("status " + location.hostname + location.pathname + " | " + s);
      if (/ again/.test(s)) report("again " + snapshot());   // had to click Continue twice: show me the page
    }
    else if (!snapped && Date.now() - since > 8000) { snapped = true; report("stuck " + snapshot()); }
    if (s === "NEED_PREFILL") window.__duoPrefillRun();
    if (typeof s === "string" && s.startsWith("DONE")) {
      clearInterval(loop);
      await GM.setValue("duo", "null");   // finished: stop acting until the next alert
    }
  }, 150);
})();
"""


def build():
    base = {"device": "phone", "zip": w.ZIP, "phone": os.environ.get("DUO_TMOBILE_NUMBER", ""),
            "pickup": {k: os.environ.get("DUO_PICKUP_" + k.upper(), "") for k in ("first", "last", "email", "phone")}}
    src = (TEMPLATE.replace("__BASE__", json.dumps(base)).replace("__LOG__", json.dumps(w.NTFY_TOPIC + "-phonelog")).replace("__LIFE__", str(LIFETIME_MIN))
           .replace("__MACLOG__", json.dumps(w.NTFY_TOPIC + "-maclog"))
           .replace("__STEP__", (HERE / "checkout.js").read_text().rstrip().rstrip(";"))
           .replace("__PREFILL__", (HERE / "prefill.js").read_text()))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(src)
    return OUT


def link(store="", store_name="", drop_item="", buy_url=""):
    """Alert link for the phone: open the bag with what the userscript needs (no personal data in it)."""
    cfg = {"store": store, "storeName": store_name, "dropItem": drop_item, "buyUrl": buy_url}
    return "https://www.apple.com/shop/bag#duo=" + urllib_quote(json.dumps(cfg, separators=(",", ":")))


def urllib_quote(s):
    from urllib.parse import quote
    return quote(s, safe="")


if __name__ == "__main__":
    print(f"wrote {build()}")
