// PS Direct checkout for the PS5 Pro, run on the phone by the userscript ps5_phone_script.py builds (it puts PS5_BASE
// and the ==UserScript== header in front of this file). It acts only in the tab opened from a PS5 alert link
// (direct.playstation.com/...?ps5={"code":...}), for PS5_BASE.life minutes:
//   product page: Add to Cart > cart: Checkout > shipping: Continue to Payment > payment: scroll to Place Order, STOP.
// It never taps Place Order, a wallet (Apple Pay, PayPal, Klarna) or anything that pays, never types an address or
// card, and never touches queue-it or bot checks: if PS Direct refuses its Add to Cart tap, it hands that tap to you.
(async () => {
  const B = PS5_BASE;
  const report = msg => { try { GM.xmlHttpRequest({ method: "POST", url: "https://ntfy.sh/" + B.log, data: "[" + B.build + "] " + msg }); } catch (e) {} };
  // the alert link carries ?ps5=<json> (a query: queue-it sends you back to the full URL, a #hash would be lost)
  let cfg = null;
  const hm = location.hash.match(/ps5=([^&]+)/);
  const raw = new URLSearchParams(location.search).get("ps5") || (hm ? decodeURIComponent(hm[1]) : null);
  if (raw) {
    try { cfg = JSON.parse(raw); } catch (e) { cfg = null; }
    if (cfg && cfg.code) { cfg.t = Date.now(); window.name = "ps5-" + cfg.t; await GM.setValue("ps5", JSON.stringify(cfg)); }
    // drop only our own parameter: after a queue-it line the URL also carries queueittoken, which PS Direct reads
    const q = new URLSearchParams(location.search); q.delete("ps5");
    history.replaceState(null, "", location.pathname + (q.toString() ? "?" + q : ""));
  } else {
    try { cfg = JSON.parse(await GM.getValue("ps5", "null")); } catch (e) { cfg = null; }
  }
  if (!cfg || !cfg.code || Date.now() - (cfg.cleanAt || cfg.t) > B.life * 60000) return;   // only right after an alert
  // only the tab the alert opened acts (an older test tab stays out); an empty or foreign name is re-tagged
  const RUN = "ps5-" + cfg.t;
  if (/^ps5-/.test(window.name) && window.name !== RUN) return;
  window.name = RUN;
  const NAME = B.names[cfg.code] || "PlayStation®5 Pro Console";
  const CART = "https://direct.playstation.com/en-us/checkout?tab=cart";
  const save = () => GM.setValue("ps5", JSON.stringify(cfg));
  const seen = el => !!el && el.getClientRects().length > 0;
  const txt = el => (el.textContent || "").replace(/\s+/g, " ").trim();
  // exact-name clicks only, and never anything that orders or pays, whatever the selector found
  const BLOCK = /place (your )?order|apple ?pay|google ?pay|paypal|klarna|pay now|pay with|submit order|buy now|confirm order|purchase/i;
  const press = (el, name) => {
    const labels = [txt(el), el.getAttribute("aria-label") || "", el.value || ""];
    if (labels.some(l => BLOCK.test(l))) { report("refused to click: " + labels.join(" / ")); return false; }
    if (!labels.includes(name)) return false;
    el.click(); return true;
  };
  // PS Direct redraws its buttons as the page loads: wait for load + 1.2 s, then look the button up again
  const loadedFor = () => {
    const n = performance.getEntriesByType("navigation")[0];
    return n && n.loadEventEnd > 0 ? performance.now() - n.loadEventEnd : document.readyState === "complete" ? 9e9 : 0;
  };
  const banner = (msg, color) => {
    let b = document.getElementById("ps5-banner");
    if (!b) { b = document.createElement("div"); b.id = "ps5-banner"; document.body.appendChild(b); }
    b.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:2147483647;padding:12px;font:600 16px -apple-system,sans-serif;text-align:center;color:#fff;pointer-events:none;background:" + (color || "#0070d1");
    b.textContent = "PS5: " + msg.replace(/^(DONE|YOUR TURN:?) ?/, m => m === "DONE " ? "" : m);
  };
  const mark = el => { el.scrollIntoView({ block: "center" }); el.style.outline = "6px solid #30d158"; el.style.outlineOffset = "4px"; };
  const ring = () => { try { const a = new (window.AudioContext || window.webkitAudioContext)(); const o = a.createOscillator(); o.frequency.value = 880; o.connect(a.destination); o.start(); o.stop(a.currentTime + 0.4); } catch (e) {} };
  let lastGo = 0;
  const go = url => { if (Date.now() - lastGo < 6000) return; lastGo = Date.now(); location.href = url; };
  const cartCount = () => { const e = document.querySelector(".js-mini-cart-count"); return e ? parseInt(e.getAttribute("data-count") || txt(e), 10) || 0 : 0; };
  // cart requests the page sent since t (responseStatus where Safari reports it): tells "PS Direct refused the tap"
  // apart from "the page ignored the tap"
  const cartCalls = t => performance.getEntriesByType("resource").filter(r => /\/carts\/[^/?]+\/entries/.test(r.name) && r.startTime >= t).map(r => r.responseStatus || "sent");
  const pageStart = Date.now();
  let clicks = 0, clickT = 0, clickPerf = 0, count0 = 0, lastCta = 0, ctaTries = 0, rang = false, doneAt = 0;

  const product = () => {
    if (loadedFor() < 1200) return "waiting for the page to load";
    if (cfg.added) { go(CART); return "in your cart - going to checkout"; }
    const btn = [...document.querySelectorAll('button.add-to-cart[data-product-code="' + cfg.code + '"]')].find(seen);
    if (clickT && cartCount() > count0) {
      cfg.added = true; save(); go(CART);
      return "added to cart (" + (clicks ? "script tap" : "your tap") + ") - going to checkout";
    }
    if (!btn) {
      const oos = document.querySelector(".js-out-stock-wrpr");
      if (seen(oos)) {
        if (cfg.test) return "DONE the test item is out of stock - pick another stand-in";
        // the feed can lead the page by a moment: reload every 15 s, but only for 5 min after the alert
        if (Date.now() - cfg.t > 5 * 60000) return "DONE still not in stock 5 min after the alert - stopped reloading";
        if (Date.now() - pageStart > 15000) location.reload();
        return "not in stock on the page yet - reloading every 15 s";
      }
      if (!/buy-consoles|accessories|games/.test(location.pathname)) { go(B.page); return "going to the PS5 Pro page"; }
      return "waiting for Add to Cart to show";
    }
    if (!clickT) count0 = cartCount();
    if ((cfg.clicks || 0) < 6 && clicks < 2 && (!clickT || Date.now() - clickT > 6000)) {
      count0 = cartCount(); clickPerf = performance.now();   // read in the same tick as the click, no extra round trip
      if (press(btn, "Add to Cart")) { clicks++; clickT = Date.now(); cfg.clicks = (cfg.clicks || 0) + 1; save(); }
      return "tapped Add to Cart (" + clicks + ")";
    }
    if (Date.now() - clickT < 6000) return "waiting for the cart to update";
    if (!clickT) { clickT = Date.now(); count0 = cartCount(); }
    mark(btn); if (!rang) { rang = true; ring(); }
    const calls = cartCalls(clickPerf);
    return "YOUR TURN: tap Add to Cart (PS Direct didn't take the script's tap: " + (calls.length ? "cart request " + calls.join(",") : "no cart request seen") + ")";
  };

  const cta = (name, what) => {
    const b = [...document.querySelectorAll("button.checkout-cta__next, button")].find(x => seen(x) && txt(x) === name);
    if (!b) return "waiting for " + name;
    if (b.disabled) return "YOUR TURN: " + what;
    if (ctaTries >= 3) return "YOUR TURN: tap " + name + " (3 script taps didn't move on)";
    if (Date.now() - lastCta > 6000 && press(b, name)) { lastCta = Date.now(); ctaTries++; }
    return "tapped " + name + (ctaTries > 1 ? " again" : "");
  };

  const cart = () => {
    if (loadedFor() < 1200) return "waiting for the cart to load";
    const body = document.body.innerText;
    const removes = [...document.querySelectorAll("button.remove-btn")].filter(seen);
    const item = b => { let e = b; for (let i = 0; i < 8 && e.parentElement && !/Qty/.test(e.textContent); i++) e = e.parentElement; return txt(e); };
    if (!removes.length && !/no items added|empty/i.test(body)) return "reading the cart...";
    const mine = removes.find(b => item(b).includes(NAME));
    if (cfg.clean) {   // dry run over: take the stand-in back out (never the Pro, never in a real run)
      if (!mine) { cfg.cleaned = true; save(); return "DONE dry run over - the test item is out of your cart"; }
      if (cfg.code === B.stand && Date.now() - lastCta > 4000 && press(mine, "Remove")) lastCta = Date.now();
      return "dry run over: removing the test item";
    }
    if (!mine) {
      if ((cfg.backs || 0) >= 2) return "DONE the item isn't in the cart and 2 tries to add it failed - add it by hand";
      cfg.backs = (cfg.backs || 0) + 1; cfg.added = false; save(); go(B.page);
      return "not in the cart - going back to add it";
    }
    cfg.others = removes.filter(b => b !== mine).map(b => item(b).replace(/ Remove.*/, "").slice(0, 40));
    if (/Guest Checkout/i.test(body)) return "YOUR TURN: sign in to your Sony account (Sign in, top right) - the cart keeps the item";
    return cta("Checkout", "Checkout is greyed out - check the cart");
  };

  const shipping = () => {
    if (loadedFor() < 1200) return "waiting for shipping to load";
    const blank = [...document.querySelectorAll("input[name=line1], input[name=firstName], input[name=lastName]")].filter(f => seen(f) && !f.value);
    if (blank.length) return "YOUR TURN: add or pick a shipping address (the script never types it), then Continue to Payment";
    return cta("Continue to Payment", "pick a shipping address and method");
  };

  const payment = () => {
    if (loadedFor() < 1200) return "waiting for payment to load";
    const place = [...document.querySelectorAll("button, input[type=submit]")].find(x => seen(x) && /place (your )?order/i.test(txt(x) || x.value || ""));
    const extra = cfg.others && cfg.others.length ? " - ALSO IN CART: " + cfg.others.join(", ") : "";
    if (!place) return "YOUR TURN: pick a payment method - Place Order isn't showing yet" + extra;
    mark(place); if (!rang) { rang = true; ring(); }
    return "DONE YOUR TURN: check the card and address, then tap Place Order" + (cfg.test ? " (dry run: DON'T)" : "") + extra;
  };

  const step = () => {
    if (!/\/checkout/.test(location.pathname)) return product();
    const tab = new URLSearchParams(location.search).get("tab") || "cart";
    if (cfg.clean && tab !== "cart") { go(CART); return "dry run over: going to the cart"; }
    return tab === "shipping" ? shipping() : tab === "payment" ? payment() : cart();
  };

  const snapshot = () => JSON.stringify({ path: location.pathname + location.search.slice(0, 40),
    btns: [...document.querySelectorAll("button")].filter(seen).map(b => (b.disabled ? "[off]" : "") + txt(b).slice(0, 30)).filter(Boolean).slice(0, 20),
    fields: [...document.querySelectorAll("input:not([type=hidden]), select")].filter(seen).map(f => (f.name || f.id) + (f.value ? "=filled" : "=EMPTY")).slice(0, 15) });
  let lastS = "", since = Date.now(), snapped = false, lastCheck = 0;
  const loop = setInterval(async () => {
    if (Date.now() - lastCheck > 1000) {   // a newer alert took over in another tab: stop here
      lastCheck = Date.now();
      let now = null;
      try { now = JSON.parse(await GM.getValue("ps5", "null")); } catch (e) {}
      if (!now || now.t !== cfg.t) { clearInterval(loop); banner("stopped - a newer run started in another tab", "#6e6e73"); return report("stopped: newer run in another tab"); }
    }
    let s;
    try { s = step(); } catch (e) { s = "script error: " + e.message; }
    if (s !== lastS) { lastS = s; since = Date.now(); snapped = false; report("status " + location.pathname + location.search.slice(0, 20) + " | " + s); }
    else if (!snapped && Date.now() - since > 8000 && !/^DONE|YOUR TURN|reloading/.test(s)) { snapped = true; report("stuck " + snapshot()); }
    banner(s, /YOUR TURN/.test(s) ? "#d70015" : /^DONE/.test(s) ? "#248a3d" : null);
    if (/^DONE/.test(s)) {
      // dry run: leave Place Order up for 20 s, then take the stand-in back out of the cart
      if (cfg.test && !cfg.clean && !cfg.cleaned && cfg.code === B.stand && /Place Order/.test(s)) {
        doneAt = doneAt || Date.now();
        if (Date.now() - doneAt > 20000) { cfg.clean = true; cfg.cleanAt = Date.now(); await save(); report("dry run done - removing the test item"); go(CART); }
        return;
      }
      clearInterval(loop); await GM.setValue("ps5", "null");   // finished: idle until the next alert
    }
  }, 250);
})();
