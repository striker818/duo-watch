// One step of the Apple checkout. checkout.py runs this in its Chrome tab every half second; each run looks at
// the page, does at most one thing, and returns what it did. "WAIT ..." means it needs you (sign-in, card,
// carrier info, anything it doesn't recognize); "DONE ..." means it reached Review. It never clicks Place Order.
// checkout.py (Mac) or the phone userscript (phone_script.py) puts `var DUO = {device, store, storeName, zip, ...}`
// in front of this.
(() => {
  const url = location.href;
  // Each device runs its own sequence. Apple serves them different checkouts: the Mac gets separate pages ending in
  // Review > Place Your Order; the phone gets one combined pickup + payment page ending in Continue with Apple Pay.
  const PHONE = DUO.device === "phone";
  const MODE = PHONE ? {
    settleMs: 250,         // phone pages are quick and haven't swallowed clicks; keep the pause short
    applePayFinal: true,   // its last page ends in Continue with Apple Pay (the Apple Pay sheet places the order)
  } : {
    settleMs: 500,         // Mac: a Continue clicked the instant a form appears gets swallowed (~9s lost), so wait a bit
    applePayFinal: false,  // its last page is Review with Place Your Order
  };
  const seen = el => !!el && (el.offsetParent !== null || el.getClientRects().length > 0);
  const vis = sel => [...document.querySelectorAll(sel)].filter(seen);
  const text = el => (el.textContent || "").replace(/\s+/g, " ").trim();
  const byText = (sel, re) => vis(sel).find(e => re.test(text(e)));
  const labelOf = r => (r.labels && r.labels[0]) || r.closest("label") || r;
  const radios = re => [...document.querySelectorAll("input[type=radio]")].filter(r => re.test(r.name) && (seen(r) || seen(labelOf(r))));
  // run fn at most once every `ms` on this page, so a click that didn't take gets retried but not spammed
  const act = (key, fn, ms = 5000) => {
    const k = "__duoAct_" + key;
    if (window[k] && Date.now() - window[k] < ms) return false;
    window[k] = Date.now(); fn(); return true;
  };
  const setValue = (el, v) => {  // React ignores plain .value = ...; go through the native setter
    const proto = el.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, v);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  };
  const say = msg => {
    let b = document.getElementById("duo-banner");
    if (!b) {
      b = document.createElement("div"); b.id = "duo-banner";
      b.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:2147483647;padding:12px;font:600 16px -apple-system;text-align:center;color:#fff;pointer-events:none";
      document.body.appendChild(b);
    }
    b.style.background = msg.startsWith("DONE") ? "#248a3d" : msg.startsWith("WAIT") ? "#d70015" : "#0071e3";
    b.textContent = "Duo checkout: " + msg.replace(/^(WAIT|DONE) /, msg.startsWith("WAIT") ? "YOUR TURN - " : "");
    return msg;
  };
  const missing = () => vis("input:not([type=hidden]):not([type=radio]):not([type=checkbox]), select")
    .filter(e => (e.required || e.getAttribute("aria-required") === "true") && !e.value && !e.disabled)
    .map(e => (e.labels && e.labels[0] ? text(e.labels[0]) : e.name || e.id));
  const placeOrder = () => byText("button", /place (your )?order/i);
  // Apple sometimes lands somewhere odd after Add to Bag (a 404, or the iPhone overview when the buy page reloads as
  // stock runs out). The phone is usually already in the bag, so go to the bag and carry on, up to 2 times.
  // The phone keeps the count in the extension's storage (DUO.rescues): page storage didn't hold it there, and on
  // 2026-11-04 it looped bag > Check Out > 404 about 35 times in 20s.
  const rescues = DUO.rescues || { get: () => +(sessionStorage.__duoRescues || 0), set: async n => { sessionStorage.__duoRescues = n; } };
  function rescue(why) {
    const n = rescues.get();
    const where = location.pathname + location.search;
    if (n >= 2) return say("WAIT " + why + " (" + where + ") - open apple.com/shop/bag and check out by hand");
    if (act("rescue", async () => { await rescues.set(n + 1); location.href = "https://www.apple.com/shop/bag"; }, 4000))
      return say("off track: " + why + " at " + where + " - reopening the bag");
    return say("reopening the bag...");
  }

  // The last page: Review on the Mac (Place Your Order), or on the phone the single pickup + payment page that ends in
  // "Continue with Apple Pay" (the Apple Pay sheet is where you confirm the order). Tick the carrier's terms, make
  // sure the other ready-cart size is gone, then scroll the final button into view and ring it. Never clicked here.
  function finish(btn, how) {
    const pageText = text(document.body);
    const stale = (DUO.dropItem || "").split("|").filter(Boolean).find(d => pageText.includes(d));
    if (stale) return act("review_refresh", () => location.reload(), 6000)
      ? say("the order still lists " + stale + " - refreshing") : say("waiting for " + stale + " to leave the order...");
    const terms = [...document.querySelectorAll("input[type=checkbox]")]
      .filter(c => !c.checked && !c.disabled && (seen(c) || seen(labelOf(c))) && /terms/i.test(c.id + " " + text(labelOf(c))));
    if (terms.length)
      return act("terms", () => labelOf(terms[0]).click(), 2000) ? say("accepted: " + text(labelOf(terms[0]))) : say("accepting terms...");
    if (btn && !window.__duoScrolled) {
      window.__duoScrolled = true;
      btn.scrollIntoView({ block: "center", behavior: "instant" });
      btn.style.outline = "6px solid #30d158"; btn.style.outlineOffset = "4px"; btn.style.borderRadius = "12px";
    }
    return say("DONE review the order and " + how);
  }

  function next(step) {
    // Apple's own Continue (any rs-checkout-continue-button*), else a button named just "Continue" / "Continue to ...".
    // Never "Continue with Apple Pay" (the phone shows one on the pickup contact page) or anything Apple Pay.
    const notPay = e => !/apple\s*pay|continue with/i.test(text(e) + " " + (e.getAttribute("aria-label") || "") + " " + e.className);
    const b = vis("button[id^=rs-checkout-continue-button]").filter(notPay)[0]
      || vis("button").filter(notPay).find(e => /^continue( to .*)?$/i.test(text(e)));
    if (!b) {
      // no Continue, just "Continue with Apple Pay": the phone's last page (the Mac doesn't normally get it, but if it
      // ever does, it's the last page there too - confirmed with Touch ID)
      const pay = vis("button, [role=button]").find(e => /^continue with/i.test(text(e)) || /apple\s*pay/i.test(e.getAttribute("aria-label") || ""));
      if (pay) {
        const m = missing();
        if (m.length) return say("WAIT fill in: " + m.join(", "));
        return finish(pay, "tap Continue with Apple Pay, then confirm with " + (MODE.applePayFinal ? "Face ID" : "Touch ID"));
      }
      return say(step + ": looking for Continue");
    }
    if (/place|order|submit|pay now/i.test(text(b))) return say("DONE review the order and tap Place Your Order yourself");
    if (b.disabled || b.getAttribute("aria-disabled") === "true") return say(step + ": waiting for Continue to enable");
    // a form that just appeared can swallow the first Continue (seen on pickup contact: Apple spent ~9s, then stayed on
    // the page and needed a second click), so let each step settle for a moment first
    const k = "__duoSeen_" + step;
    if (!window[k]) window[k] = Date.now();
    if (Date.now() - window[k] < MODE.settleMs) return say(step + ": letting the form settle");
    // clicking again on the same step: note what the page complained about, to fix next time
    const again = window["__duoAct_next_" + step];
    const errs = again ? vis("[role=alert], .form-message-error, [class*=error-message], [class*=errorMessage]").map(text).filter(Boolean).slice(0, 2).join(" / ") : "";
    if (act("next_" + step, () => b.click())) return say(step + ": clicked " + text(b) + (again ? " again" + (errs ? " (page said: " + errs + ")" : "") : ""));
    return say(step + ": continuing...");
  }

  function fulfillment() {
    const stores = radios(/store/i);
    if (!stores.length) {
      const pickup = byText("button", /pick it up/i);
      if (pickup && act("pickup", () => pickup.click())) return say("chose I'll pick it up");
      const box = vis("input[type=text], input[type=search], input[type=tel]").find(e => /storeLocator|store.*search|search.*store/i.test(e.id + e.name));
      if (box && DUO.zip && act("search", () => {
        setValue(box, DUO.zip);
        const go = vis("button").find(b => /storeLocator|store.*search/i.test(b.id) && /search|apply|find|go/i.test(text(b) + b.getAttribute("aria-label")));
        go ? go.click() : box.form && box.form.requestSubmit();
      }, 8000)) return say("searching stores near " + DUO.zip);
      return say("waiting for the store list");
    }
    let want = stores.find(r => DUO.store && r.value === DUO.store)
      || stores.find(r => DUO.storeName && text(labelOf(r)).includes(DUO.storeName));
    // Apple lists stores near where it thinks you are (on cellular the phone often geolocates to Chicago, 2026-11-10).
    // The alerted store missing from the list means the wrong area: search your ZIP before calling it sold out, and
    // never fall back to "any other store" from a list that was never searched near your ZIP.
    if (!want && DUO.zip) {
      const box = vis("input[type=text], input[type=search], input[type=tel]").find(e => /storeLocator|store.*search|search.*store|zip|postal|location/i.test(e.id + e.name + (e.getAttribute("aria-label") || "") + (e.placeholder || "")));
      if (!box) {
        const open = vis("button, a").find(b => /storeLocator|store.*search|change.*location/i.test((b.id || "") + (b.getAttribute("data-autom") || ""))
          || /^(change|edit|search)\b|show stores near|other stores|change location/i.test(text(b)));
        if (open && act("storesearch_open", () => open.click(), 3000)) return say("opening the store search to look near " + DUO.zip);
        window.__duoZipLook = window.__duoZipLook || Date.now();
        if (Date.now() - window.__duoZipLook < 6000) return say("looking for the store search box (the list isn't near " + DUO.zip + ")");
      } else if (box.value.replace(/\s/g, "") !== DUO.zip || !window.__duoZipSearched) {
        if (act("search_zip", () => {
          window.__duoZipTries = (window.__duoZipTries || 0) + 1; window.__duoZipSearched = true;
          setValue(box, DUO.zip);
          const go = vis("button").find(b => /storeLocator|store.*search/i.test(b.id + (b.getAttribute("data-autom") || "")) && /search|apply|find|go/i.test(text(b) + (b.getAttribute("aria-label") || "")));
          go ? go.click() : box.form ? box.form.requestSubmit() : box.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", keyCode: 13, bubbles: true }));
        }, 4000)) return say("the store list isn't near you - searching stores near " + DUO.zip);
        return say("waiting for stores near " + DUO.zip);
      }
      if (!window.__duoZipSearched) return say("WAIT the pickup list shows stores far from " + DUO.zip + " - search " + DUO.zip + " and pick " + (DUO.storeName || "your store"));
    }
    if (!want || want.disabled) {
      // the alerted store sold out (or isn't listed): take any other nearby store that still offers pickup
      const other = stores.find(r => r.checked && !r.disabled) || stores.find(r => !r.disabled);
      if (!other) return say("WAIT " + (DUO.storeName || "the store") + " sold out and no other store nearby offers pickup right now");
      const name = text(labelOf(other)).slice(0, 40);
      if (!other.checked) return act("store_alt", () => labelOf(other).click(), 1500)
        ? say("switched store: " + (DUO.storeName || "store") + " sold out, picked " + name) : say("selecting another store...");
      want = other;
    }
    if (!want.checked) return act("store", () => labelOf(want).click(), 1500) ? say("picked " + DUO.storeName) : say("selecting the store...");
    // earliest pickup day/time: Apple shows either a <select> or radio groups, depending on the store
    const sel = vis("select").find(e => /time|slot|date/i.test(e.id + e.name) && !e.value);
    const opt = sel && [...sel.options].find(o => o.value && !o.disabled);
    if (opt) { setValue(sel, opt.value); return say("chose pickup time " + text(opt)); }
    const slots = radios(/time|slot|date|day/i);
    for (const name of new Set(slots.map(r => r.name))) {
      const group = slots.filter(r => r.name === name);
      const first = group.find(r => !r.disabled);
      if (!group.some(r => r.checked) && first)
        return act("slot_" + name, () => labelOf(first).click(), 3000) ? say("chose the earliest pickup slot") : say("selecting pickup slot...");
    }
    return next("pickup");
  }

  function contact() {
    // someone else picks up (DUO.pickup from local.env): choose that option and fill in their details
    const pk = DUO.pickup || {};
    if (pk.first) {
      const other = vis("button[data-autom=thirdPartyPickup]")[0] || byText("button", /someone else will pick it up/i);
      const first = vis("input[name=firstName]")[0];
      if (!first) return other && act("thirdparty", () => other.click(), 3000) ? say("chose Someone else will pick it up") : say("waiting for the pickup form");
      // the first email/phone on the page are the pickup person's; yours further down are prefilled from your account
      const want = { firstName: pk.first, lastName: pk.last, emailAddress: pk.email, fullDaytimePhone: pk.phone };
      // Apple usually prefills the right person now, so this normally does nothing; it only steps in for a blank or a
      // different value (an old pickup person). Masked values (t•••8@gmail.com) mean Apple already has it: leave them.
      // Phones compare by digits since Apple reformats them as (651) 366-...
      const norm = (name, v) => name === "fullDaytimePhone" ? String(v).replace(/\D/g, "") : String(v).trim().toLowerCase();
      const filled = [];
      for (const [name, v] of Object.entries(want)) {
        const box = vis(`input[name=${name}]`)[0];
        if (box && v && !box.value.includes("•") && norm(name, box.value) !== norm(name, v) && act("fill_" + name, () => setValue(box, v), 1000))
          filled.push(name);
      }
      if (filled.length) return say("filled in pickup person " + pk.first + " " + (pk.last || "") + " (" + filled.join(", ") + ")");
    }
    const m = missing();
    return m.length ? say("WAIT fill in the pickup contact: " + m.join(", ")) : next("pickup contact");
  }

  function billing() {
    // Apple Card Monthly Installments only when financing (DUO.financing); the payment page can offer it on a paid-in-full
    // order too, and choosing it there would turn the order into financing
    const acmi = DUO.financing && radios(/./).find(r => /apple card monthly/i.test(text(labelOf(r))));
    if (acmi && !acmi.checked)
      return act("acmi", () => labelOf(acmi).click(), 3000) ? say("chose Apple Card Monthly Installments") : say("selecting Apple Card...");
    // paying in full: Apple Pay, not the saved card Apple preselects (value APPLE_PAY, label "Apple Pay")
    const applePay = !DUO.financing && radios(/billing/i).find(r => /APPLE_PAY/i.test(r.value) || /^\s*apple pay/i.test(text(labelOf(r))));
    if (applePay && !applePay.checked)
      return act("applepay", () => labelOf(applePay).click(), 3000) ? say("chose Apple Pay") : say("selecting Apple Pay...");
    const m = missing();
    return m.length ? say("WAIT payment needs you: " + m.join(", ")) : next("payment");
  }

  if (!/^https?:/.test(url)) return "page loading...";   // Safari's new window is about:blank for a moment
  if (/\/shop\/404/.test(url) || /page not found/i.test(document.title)) return rescue("Apple showed a 404");
  if (placeOrder()) return finish(placeOrder(), "tap Place Your Order yourself");
  if (/\/shop\/signIn/i.test(url) || /^idmsa\./.test(location.hostname)) return say(  // idmsa: Apple Card checkout sign-in
    "WAIT sign in to your Apple Account - I'll carry on after that");
  if (/^preauth/.test(location.hostname)) {  // "Let's connect this new iPhone to T-Mobile": number, PIN, picture code
    const num = vis("input").find(e => /wireless number|phone number/i.test(e.labels && e.labels[0] ? text(e.labels[0]) : e.getAttribute("aria-label") || ""));
    if (num && DUO.phone && !num.value) { setValue(num, DUO.phone); return say("filled in your T-Mobile number"); }
    return say("WAIT enter your T-Mobile PIN and the picture code, then Continue (and the texted code if asked)");
  }
  if (/[?&]step=attach/.test(url)) {      // accessories page Apple shows after Add to Bag
    const b = byText("button[data-autom=proceed], a, button", /^(review|view|go to) bag/i);
    if (!b) return say("waiting for Review Bag");
    return act("reviewbag", () => b.click()) ? say("clicked Review Bag") : say("opening the bag...");
  }
  if (/\/shop\/buy-iphone\//.test(url)) {  // prefill.js does this page; after Add to Bag, follow a Review Bag link if one shows
    const bag = window.__duoPrefill && /^adding/.test(window.__duoPrefill) && byText("a, button", /^(review|view|go to) bag/i);
    if (bag && act("reviewbag", () => bag.click())) return "clicked Review Bag";
    // Add to Bag clicked but nothing happened (no Review Bag, no new page): click it again, at most twice, 4s apart
    const atb = !bag && window.__duoPrefill && /^adding/.test(window.__duoPrefill) && vis("button[data-autom=add-to-cart]").find(e => !e.disabled && e.getAttribute("aria-busy") !== "true");
    if (atb) {
      window.__duoAddAt = window.__duoAddAt || Date.now();
      window.__duoAddTries = window.__duoAddTries || 0;
      if (Date.now() - window.__duoAddAt > 4000 * (window.__duoAddTries + 1) && window.__duoAddTries < 2) {
        window.__duoAddTries++; atb.click(); return "Add to Bag didn't take - clicked it again (" + window.__duoAddTries + ")";
      }
    }
    return window.__duoPrefill ? "prefill: " + window.__duoPrefill : "NEED_PREFILL";
  }
  if (/\/shop\/product\//.test(url)) {     // --test runs on an accessory page
    const b = document.querySelector("button[data-autom=add-to-cart]");
    return b && !b.disabled && act("bag", () => b.click()) ? say("clicked Add to Bag") : say("adding to bag...");
  }
  if (/\/shop\/bag/.test(url)) {
    // the Mac already took this bag into checkout: don't start a second checkout of it (Apple answered the phone's
    // Check Out with a 404 when both did). The phone script shows a button to move the checkout here instead.
    // macBusy is undefined until the phone script's first look at the Mac's state comes back (~0.3s): in the dry run
    // the phone clicked Check Out in that gap and got the same 404
    if (PHONE && DUO.macBusy === undefined && !DUO.takeover) return say("checking whether the Mac is already checking out...");
    if (PHONE && DUO.macBusy && !DUO.takeover) return say("WAIT the Mac is already checking out - finish there, or tap Check out on this phone");
    if (/bag is empty/i.test(document.body.innerText)) {
      // started from the ready cart but it's gone (Apple cleared it): fall back to the buy page
      if (DUO.buyUrl && act("tobuy", () => { location.href = DUO.buyUrl; }, 8000)) return say("the ready cart was empty - opening the buy page");
      return say("WAIT the bag is empty - nothing got added");
    }
    const removes = vis("button[data-autom=bag-item-remove-button]");
    // ready cart with a different size in stock: take the other size out first. It can't wait until after Check Out:
    // Apple refuses to check out more than one carrier-connected iPhone at a time ("You can only order one
    // carrier-connected device at a time"). If it's the only item, the bag empties and we fall back to the buy page.
    const drops = (DUO.dropItem || "").split("|").filter(Boolean);
    const extra = removes.filter(b => drops.some(d => text(b).includes(d)));
    if (extra.length)
      return act("drop", () => extra[0].click(), 1500) ? say("removed " + text(extra[0]).replace(/^Remove/, "") + " from the bag (not the size in stock)") : say("removing the other size...");
    // leftovers in the bag would go into the same order; let you decide rather than check out with them
    const items = removes.length - extra.length;
    // a ready-cart line at quantity 2+ would order 2 phones: set it to 1 before checking out
    const q2 = [...document.querySelectorAll("select")].find(x => /itemQuantity/.test(x.name || x.id) && +x.value > 1);
    if (q2) {
      if (act("qty1", () => { Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(q2, "1");
        q2.dispatchEvent(new Event("input", { bubbles: true })); q2.dispatchEvent(new Event("change", { bubbles: true })); }, 4000))
        return say("set quantity back to 1");
      return say("waiting for the quantity to update...");
    }
    if (items > 1) return say("WAIT the bag has " + items + " items - remove all but the phone, then I'll check out");
    // with Apple Card Monthly the button is bag-checkout-button, and the first click opens an Apple Card pop-up that
    // has its own copy of it; click the pop-up's one when it's open, or we just keep reopening the pop-up
    const sel = "button[data-autom=checkout], button[data-autom=bag-checkout-button]";
    const pop = vis(`[aria-modal=true] :is(${sel}), [role=dialog] :is(${sel})`)[0];
    if (pop) return act("checkout_popup", () => pop.click(), 2000) ? say("clicked Check Out in the Apple Card pop-up") : say("opening checkout...");
    const b = vis(sel)[0];
    if (!b) return say("waiting for Check Out");
    // Check Out tapped before Apple's page script takes over the button goes to Apple's raw checkout link and gets a
    // 404 (2026-11-05: three taps 0-1s after the bag loaded all 404'd; the one that worked opened the Apple Card
    // pop-up first, which only the page script does). Wait until the page has loaded plus a moment.
    const nav = performance.getEntriesByType("navigation")[0];
    const loadedFor = nav && nav.loadEventEnd > 0 ? performance.now() - nav.loadEventEnd : document.readyState === "complete" ? 9e9 : 0;
    if (loadedFor < 1200) return say("waiting for the bag page to finish loading");
    return act("checkout", () => b.click()) ? say("clicked Check Out") : say("opening checkout...");
  }
  if (/\/checkout/.test(url)) {
    const step = (url.match(/_s=([A-Za-z]+)/) || [])[1] || "";
    if (/^Fulfillment/i.test(step)) return fulfillment();
    if (/^PickupContact/i.test(step)) return contact();
    if (/^Billing/i.test(step)) return billing();
    if (!step || /processing/i.test(document.title)) return say("loading checkout...");  // brief page after sign-in
    if (/^Review/i.test(step)) {
      // paid with Apple Pay, the last button is Apple's Apple Pay button instead of Place Your Order; it opens the Apple
      // Pay sheet, where you confirm. Never clicked here.
      const pay = vis("button, [role=button], apple-pay-button, [class*=apple-pay]").find(e => /apple\s*pay/i.test(text(e) + " " + (e.getAttribute("aria-label") || "") + " " + (e.className || "") + " " + e.tagName));
      if (pay) return finish(pay, "tap the Apple Pay button, then confirm with " + (PHONE ? "Face ID" : "Touch ID"));
      return say("loading the order review...");                  // Place Your Order not drawn yet
    }
    return say("WAIT checkout step '" + step + "' needs you");
  }
  if (/(^|\.)apple\.com$/.test(location.hostname)) return rescue("unexpected page '" + document.title + "'");
  return say("WAIT unexpected page (" + document.title + ") - take over");
})();
