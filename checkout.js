// One step of the Apple checkout. checkout.py runs this in its Chrome tab every half second; each run looks at
// the page, does at most one thing, and returns what it did. "WAIT ..." means it needs you (sign-in, card,
// carrier info, anything it doesn't recognize); "DONE ..." means it reached Review. It never clicks Place Order.
// checkout.py puts `var DUO = {store, storeName, zip, phone, pickup}` in front of this.
(() => {
  const url = location.href;
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

  function next(step) {
    const b = [document.getElementById("rs-checkout-continue-button-bottom")].find(seen) || byText("button", /^continue\b/i);
    if (!b) return say(step + ": looking for Continue");
    if (/place|order|submit|pay now/i.test(text(b))) return say("DONE review the order and tap Place Your Order yourself");
    if (b.disabled || b.getAttribute("aria-disabled") === "true") return say(step + ": waiting for Continue to enable");
    if (act("next_" + step, () => b.click())) return say(step + ": clicked " + text(b));
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
    const want = stores.find(r => DUO.store && r.value === DUO.store)
      || stores.find(r => DUO.storeName && text(labelOf(r)).includes(DUO.storeName));
    if (!want) return say("WAIT pick " + (DUO.storeName || "a store") + " for pickup - I couldn't find it in the list");
    if (want.disabled) return say("WAIT " + DUO.storeName + " no longer offers pickup - pick another store");
    if (!want.checked) return act("store", () => labelOf(want).click(), 3000) ? say("picked " + DUO.storeName) : say("selecting the store...");
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
      const filled = [];
      for (const [name, v] of Object.entries(want)) {
        const box = vis(`input[name=${name}]`)[0];
        if (box && v && !box.value) { setValue(box, v); filled.push(name); }
      }
      if (filled.length) return say("filled in pickup person " + pk.first + " " + (pk.last || "") + " (" + filled.join(", ") + ")");
    }
    const m = missing();
    return m.length ? say("WAIT fill in the pickup contact: " + m.join(", ")) : next("pickup contact");
  }

  function billing() {
    const acmi = radios(/./).find(r => /apple card monthly/i.test(text(labelOf(r))));
    if (acmi && !acmi.checked)
      return act("acmi", () => labelOf(acmi).click(), 3000) ? say("chose Apple Card Monthly Installments") : say("selecting Apple Card...");
    const m = missing();
    return m.length ? say("WAIT payment needs you: " + m.join(", ")) : next("payment");
  }

  if (!/^https?:/.test(url)) return "page loading...";   // Safari's new window is about:blank for a moment
  if (/\/shop\/404/.test(url)) return say("WAIT Apple showed a 404 - open apple.com/shop/bag and check out by hand");
  if (placeOrder()) return say("DONE review the order and tap Place Your Order yourself");
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
    return window.__duoPrefill ? "prefill: " + window.__duoPrefill : "NEED_PREFILL";
  }
  if (/\/shop\/product\//.test(url)) {     // --test runs on an accessory page
    const b = document.querySelector("button[data-autom=add-to-cart]");
    return b && !b.disabled && act("bag", () => b.click()) ? say("clicked Add to Bag") : say("adding to bag...");
  }
  if (/\/shop\/bag/.test(url)) {
    if (/bag is empty/i.test(document.body.innerText)) return say("WAIT the bag is empty - nothing got added");
    // leftovers in the bag would go into the same order; let you decide rather than check out with them
    const items = vis("button[data-autom=bag-item-remove-button]").length;
    if (items > 1) return say("WAIT the bag has " + items + " items - remove all but the phone, then I'll check out");
    // with Apple Card Monthly the button is bag-checkout-button, and the first click opens an Apple Card pop-up that
    // has its own copy of it; click the pop-up's one when it's open, or we just keep reopening the pop-up
    const sel = "button[data-autom=checkout], button[data-autom=bag-checkout-button]";
    const b = vis(`[aria-modal=true] :is(${sel}), [role=dialog] :is(${sel})`)[0] || vis(sel)[0];
    if (!b) return say("waiting for Check Out");
    return act("checkout", () => b.click()) ? say("clicked Check Out") : say("opening checkout...");
  }
  if (/\/checkout/.test(url)) {
    const step = (url.match(/_s=([A-Za-z]+)/) || [])[1] || "";
    if (/^Fulfillment/i.test(step)) return fulfillment();
    if (/^PickupContact/i.test(step)) return contact();
    if (/^Billing/i.test(step)) return billing();
    if (!step || /processing/i.test(document.title)) return say("loading checkout...");  // brief page after sign-in
    if (/^Review/i.test(step)) return say("loading the order review...");                  // Place Your Order not drawn yet
    return say("WAIT checkout step '" + step + "' needs you");
  }
  return say("WAIT unexpected page (" + document.title + ") - take over");
})();
