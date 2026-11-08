// Pre-fills the iPhone Duo buy page: No trade-in -> Buy (pay in full) -> Connect to any carrier later -> No AppleCare -> Add to Bag.
// With DUO.financing (duo_watch.FINANCING): Finance -> Apple Card Monthly Installments -> T-Mobile instead, then Continue (to T-Mobile) or Add to Bag.
// Never checks out. checkout.py injects it into the buy page in Chrome via AppleScript, then takes over after Add to Bag.
// Progress/result is left in window.__duoPrefill and shown in a banner at the top of the page.
(async () => {
  const ADD_TO_BAG = !window.__duoNoBag;      // set window.__duoNoBag = true first to stop before Add to Bag
  const FINANCE = typeof DUO !== "undefined" && !!DUO.financing;
  const CARRIER = FINANCE ? "TMOBILE_" : "UNLOCKED";          // carrierModel values: TMOBILE_IPHONEDUO, UNLOCKED/US
  const CARRIER_NAME = FINANCE ? "T-Mobile" : "Connect to any carrier later";
  const CHOICES = FINANCE ? "Apple Card, T-Mobile, no AppleCare" : "Buy (pay in full), unlocked, no AppleCare";
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const banner = document.createElement("div");
  banner.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:99999;padding:10px;font:600 15px -apple-system;text-align:center;color:#fff;background:#0071e3";
  document.body.appendChild(banner);
  const status = (msg, color) => { window.__duoPrefill = msg; banner.textContent = "Duo pre-fill: " + msg; if (color) banner.style.background = color; };

  // the radios are visually hidden; find the one whose card (label) is on screen
  const shown = sel => [...document.querySelectorAll(sel)].find(e => e.offsetParent || (e.labels && e.labels[0] && e.labels[0].offsetParent));
  async function pick(sel, name, done) {           // done(): another sign it's already chosen (e.g. a collapsed summary)
    for (let i = 0; i < 130; i++) {                // ~20s: later sections stay disabled until earlier ones are answered
      if (done && done()) return;
      if ([...document.querySelectorAll(sel)].some(e => e.checked)) return;   // already chosen, even if its section is collapsed
      const el = shown(sel);
      if (el && !el.disabled) {
        ((el.labels && el.labels[0]) || el).click();
        for (let j = 0; j < 8 && !el.checked; j++) await sleep(50);   // usually takes effect in well under 400ms
        if (el.checked) return;
        el.click();
      }
      await sleep(150);
    }
    throw new Error("could not select " + name);
  }
  const summary = () => document.querySelector("[data-autom=purchaseoption-edit-link]");
  const acmiChosen = () => !!summary() && /Apple Card Monthly/i.test(summary().closest("div").parentElement.textContent);

  try {
    // wait for the page to finish drawing its option cards, or the checks below see a half-built page
    for (let i = 0; i < 100 && !document.querySelector("input[name=carrierModel]"); i++) await sleep(100);
    await sleep(150);
    // payment stays disabled until trade-in is answered; pick No trade-in unless something is already chosen
    if (document.querySelector("input[name=tradeupinline]") && !document.querySelector("input[name=tradeupinline]:checked")) {
      status("choosing No trade-in...");
      await pick("input[name=tradeupinline][value=noTradeIn]", "No trade-in");
    }
    const fullChosen = () => [...document.querySelectorAll("input[name=purchase_option_group][value=fullprice]")].some(e => e.checked);
    if (!FINANCE) {
      // the -unlocked link opens with Buy chosen; the page remembers earlier choices, so reopen it if it says otherwise
      if (summary() && !fullChosen() && !/^\s*Buy/i.test(summary().closest("div").parentElement.textContent)) { summary().click(); await sleep(300); }
      if (!fullChosen() && !summary()) { status("choosing Buy (pay in full)..."); await pick("input[name=purchase_option_group][value=fullprice]", "Buy"); await sleep(300); }
    }
    if (FINANCE) status("choosing Finance...");
    // the page remembers earlier choices; reopen the payment section unless it already says Apple Card
    if (FINANCE && summary() && !acmiChosen()) { summary().click(); await sleep(300); }
    if (FINANCE && !acmiChosen()) {
      await pick("input[name=purchase_option_group][value=finance]", "Finance");
      status("choosing Apple Card Monthly Installments...");
      // the link often preselects it, and the section collapses to a summary before we get here
      await pick("input[data-autom=purchaseOptionbfi]", "Apple Card Monthly Installments", acmiChosen);
      await sleep(600);                             // payment section collapses, then carriers re-enable
    }
    status("choosing " + CARRIER_NAME + "...");     // choosing Finance clears the carrier
    await pick(`input[name=carrierModel][value^="${CARRIER}"]`, CARRIER_NAME);
    status("choosing No AppleCare...");
    await pick("input[data-autom=noapplecare]", "No AppleCare");
    // carrier iPhones show Continue (to the T-Mobile account check) instead of Add to Bag until the carrier is verified
    let bag, proceed;
    for (let i = 0; i < 70; i++) {                 // ~10s
      // going fast, the carrier can get cleared as the payment section settles; pick T-Mobile again if so
      if (!document.querySelector("input[name=carrierModel]:checked")) {
        const tm = shown(`input[name=carrierModel][value^="${CARRIER}"]`);
        if (tm && !tm.disabled) ((tm.labels && tm.labels[0]) || tm).click();
      }
      // the AppleCare section can redraw after our click (seen in Safari) and drop the choice; pick it again
      if (!document.querySelector("input[name=applecare-options]:checked")) {
        const ac = shown("input[data-autom=noapplecare]");
        if (ac && !ac.disabled) ((ac.labels && ac.labels[0]) || ac).click();
      }
      bag = shown("button[data-autom=add-to-cart]"); proceed = shown("button[data-autom=proceed]");
      if ((bag && !bag.disabled) || (proceed && !proceed.disabled)) break;
      await sleep(150);
    }
    if (!ADD_TO_BAG) return status("ready - " + CHOICES + " selected (stopped before " + (bag ? "Add to Bag" : "Continue") + ")", "#248a3d");
    // the radios update the form a moment after they look selected; clicking before that makes Apple reload the
    // buy page (seen when going fast), so wait until the form carries T-Mobile + Apple Card + no AppleCare
    const formReady = b => {
      if (!b || !b.form) return true;
      const d = new FormData(b.form);
      return !!d.get("product") && (d.get("cppart") || "").startsWith(CARRIER) && d.get("purchaseOption") === (FINANCE ? "bfi" : "fullPrice")
        && (d.get("acpart") === null || d.get("acpart") === "none");
    };
    const go = bag && !bag.disabled ? bag : proceed;
    for (let i = 0; i < 40 && !formReady(go); i++) await sleep(75);   // up to ~3s, usually a few hundred ms
    // Add to Bag clicked before Apple's page script has taken over posts the raw form and gets a 404
    // (2026-11-08 phone: every click ~1s after the page opened went to a 404 at ...&step=select&atbtoken=...).
    // Same as Check Out on the bag: wait until the page has finished loading plus a moment.
    const loadedFor = () => { const n = performance.getEntriesByType("navigation")[0]; return n && n.loadEventEnd > 0 ? performance.now() - n.loadEventEnd : document.readyState === "complete" ? 9e9 : 0; };
    for (let i = 0; i < 100 && loadedFor() < 1200; i++) { status("waiting for the page to finish loading before Add to Bag"); await sleep(100); }
    if (bag && !bag.disabled) { status("adding to bag - checkout continues on its own", "#248a3d"); bag.click(); }
    else if (proceed && !proceed.disabled) { status("continuing to T-Mobile", "#248a3d"); proceed.click(); }
    else throw new Error("neither Add to Bag nor Continue is enabled");
  } catch (e) {
    status("stopped: " + e.message + " - finish the choices by hand", "#d70015");
  }
})();
