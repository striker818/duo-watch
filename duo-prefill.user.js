// ==UserScript==
// @name         Duo checkout helper
// @description  Only when opened from a duo-watch alert link (#duo=<store>): picks No AppleCare, adds to bag, selects the in-stock pickup store and continues to Apple's sign-in page. Never signs in or places an order.
// @match        https://www.apple.com/shop/buy-iphone/iphone-duo*
// @match        https://www.apple.com/shop/bag*
// @run-at       document-idle
// @version      1
// ==/UserScript==
(async () => {
  const KEY = "duoFlow", MAX_AGE = 10 * 60 * 1000;
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const load = () => { try { return JSON.parse(sessionStorage.getItem(KEY)) || null; } catch (e) { return null; } };
  const save = f => sessionStorage.setItem(KEY, JSON.stringify(f));
  const end = () => sessionStorage.removeItem(KEY);

  // the alert link carries #duo=<store number>, e.g. #duo=R007; nothing runs on normal visits
  const m = location.hash.match(/^#duo=(R\d+)?/);
  if (m) { save({ store: m[1] || "", stage: "product", ts: Date.now() }); history.replaceState(null, "", location.pathname + location.search); }
  const flow = load();
  if (!flow || Date.now() - flow.ts > MAX_AGE) return end();

  const banner = document.createElement("div");
  banner.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:99999;padding:10px;font:600 15px -apple-system;text-align:center;color:#fff;background:#0071e3";
  document.body.appendChild(banner);
  const status = (msg, color) => { banner.textContent = "Duo helper: " + msg; if (color) banner.style.background = color; };
  const stop = msg => { end(); status("stopped: " + msg + " - finish by hand", "#d70015"); };
  const waitFor = async (fn, ms = 15000) => { for (let t = 0; t < ms; t += 300) { const v = fn(); if (v) return v; await sleep(300); } return null; };
  // radios are visually hidden; use the one whose card is on screen
  const shown = sel => [...document.querySelectorAll(sel)].find(e => e.offsetParent || (e.labels && e.labels[0] && e.labels[0].offsetParent));
  async function pick(sel, name) {
    for (let i = 0; i < 40; i++) {
      const el = shown(sel);
      if (el && el.checked) return;
      if (el && !el.disabled) { ((el.labels && el.labels[0]) || el).click(); await sleep(400); if (el.checked) return; el.click(); }
      await sleep(500);
    }
    throw new Error("could not select " + name);
  }

  try {
    const path = location.pathname, step = new URLSearchParams(location.search).get("step");

    if (path.startsWith("/shop/buy-iphone/iphone-duo") && step === "attach") {
      // accessories page shown after Add to Bag
      if (flow.stage !== "added") return stop("unexpected page");
      status("added - opening bag...");
      return location.assign("/shop/bag");
    }

    if (path.startsWith("/shop/buy-iphone/iphone-duo/")) {
      if (flow.stage !== "product") return end();
      // the alert link presets Apple Card Monthly Installments + T-Mobile; make sure, then do AppleCare
      status("checking Apple Card + T-Mobile...");
      const summary = await waitFor(() => document.querySelector("[data-autom=purchaseoption-edit-link]"));
      if (!summary || !/Apple Card Monthly/i.test(summary.closest("div").parentElement.textContent)) {
        await pick("input[name=purchase_option_group][value=finance]", "Finance");
        await pick("input[data-autom=purchaseOptionbfi]", "Apple Card Monthly Installments");
        await sleep(2000);
      }
      await pick("input[name=carrierModel][value=TMOBILE_IPHONEDUO]", "T-Mobile");
      status("choosing No AppleCare...");
      await pick("input[data-autom=noapplecare]", "No AppleCare");
      const bag = await waitFor(() => { const b = document.querySelector("button[data-autom=add-to-cart]"); return b && !b.disabled && b; }, 10000);
      if (!bag) throw new Error("Add to Bag is not enabled");
      status("adding to bag...", "#248a3d");
      save({ ...flow, stage: "added" });
      return bag.click();
    }

    if (path.startsWith("/shop/bag")) {
      if (flow.stage !== "added") return end();
      const checkout = await waitFor(() => document.querySelector("[data-autom=bag-checkout-button]"));
      if (!checkout) return stop("bag did not load");
      // one quantity picker per bag line; saved-for-later items don't have one
      const qty = [...document.querySelectorAll("select")].filter(s => /Quantity for iPhone Duo/i.test(s.getAttribute("aria-label") || s.labels?.[0]?.textContent || ""));
      if (qty.length > 1 || (qty[0] && qty[0].value !== "1")) return stop("more than one iPhone Duo in the bag");

      if (flow.store) {
        status("selecting pickup store...");
        document.querySelector("[data-autom=bag-seemorestores-link]")?.click();
        const radio = await waitFor(() => document.querySelector(`input[name=store-locator-result][value=${flow.store}]`), 8000);
        if (radio && !radio.disabled) {
          (radio.labels[0] || radio).click(); await sleep(500);
          document.querySelector("[data-autom=bag-storelocator-confirmstore]")?.click();
          await sleep(2000);
        } else {
          document.querySelector("[data-autom=overlay-close]")?.click(); await sleep(500);
          status("store " + flow.store + " not selectable here - pick it at checkout", "#b36200"); await sleep(1500);
        }
      }

      status("going to checkout...");
      save({ ...flow, stage: "checkout" });
      checkout.click();
      // Apple Card Monthly Installments shows an info overlay with its own Check Out button
      const dlg = await waitFor(() => [...document.querySelectorAll("[role=dialog] a, [role=dialog] button")]
        .find(e => e.offsetParent && /^Check Out/i.test(e.textContent.trim())), 8000);
      end();
      if (dlg) dlg.click();
      status("sign in to finish checkout", "#248a3d");
    }
  } catch (e) {
    stop(e.message);
  }
})();
