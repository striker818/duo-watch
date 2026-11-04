// Pre-fills the iPhone Duo buy page: No trade-in -> Finance -> Apple Card Monthly Installments -> T-Mobile -> No AppleCare -> Continue (to T-Mobile) or Add to Bag.
// Never checks out. checkout.py injects it into the buy page in Chrome via AppleScript, then takes over after Add to Bag.
// Progress/result is left in window.__duoPrefill and shown in a banner at the top of the page.
(async () => {
  const ADD_TO_BAG = !window.__duoNoBag;      // set window.__duoNoBag = true first to stop before Add to Bag
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const banner = document.createElement("div");
  banner.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:99999;padding:10px;font:600 15px -apple-system;text-align:center;color:#fff;background:#0071e3";
  document.body.appendChild(banner);
  const status = (msg, color) => { window.__duoPrefill = msg; banner.textContent = "Duo pre-fill: " + msg; if (color) banner.style.background = color; };

  // the radios are visually hidden; find the one whose card (label) is on screen
  const shown = sel => [...document.querySelectorAll(sel)].find(e => e.offsetParent || (e.labels && e.labels[0] && e.labels[0].offsetParent));
  async function pick(sel, name, done) {           // done(): another sign it's already chosen (e.g. a collapsed summary)
    for (let i = 0; i < 40; i++) {                 // ~20s: later sections stay disabled until earlier ones are answered
      if (done && done()) return;
      if ([...document.querySelectorAll(sel)].some(e => e.checked)) return;   // already chosen, even if its section is collapsed
      const el = shown(sel);
      if (el && !el.disabled) {
        ((el.labels && el.labels[0]) || el).click(); await sleep(400);
        if (el.checked) return;
        el.click();
      }
      await sleep(500);
    }
    throw new Error("could not select " + name);
  }
  const summary = () => document.querySelector("[data-autom=purchaseoption-edit-link]");
  const acmiChosen = () => !!summary() && /Apple Card Monthly/i.test(summary().closest("div").parentElement.textContent);

  try {
    // wait for the page to finish drawing its option cards, or the checks below see a half-built page
    for (let i = 0; i < 20 && !document.querySelector("input[name=carrierModel]"); i++) await sleep(500);
    await sleep(500);
    // payment stays disabled until trade-in is answered; pick No trade-in unless something is already chosen
    if (document.querySelector("input[name=tradeupinline]") && !document.querySelector("input[name=tradeupinline]:checked")) {
      status("choosing No trade-in...");
      await pick("input[name=tradeupinline][value=noTradeIn]", "No trade-in");
    }
    status("choosing Finance...");
    // the page remembers earlier choices; reopen the payment section unless it already says Apple Card
    if (summary() && !acmiChosen()) { summary().click(); await sleep(800); }
    if (!acmiChosen()) {
      await pick("input[name=purchase_option_group][value=finance]", "Finance");
      status("choosing Apple Card Monthly Installments...");
      // the link often preselects it, and the section collapses to a summary before we get here
      await pick("input[data-autom=purchaseOptionbfi]", "Apple Card Monthly Installments", acmiChosen);
      await sleep(2000);                            // payment section collapses, then carriers re-enable
    }
    status("choosing T-Mobile...");                 // choosing Finance clears the carrier
    await pick("input[name=carrierModel][value^=TMOBILE_]", "T-Mobile");  // TMOBILE_IPHONEDUO, TMOBILE_IPHONE17...
    status("choosing No AppleCare...");
    await pick("input[data-autom=noapplecare]", "No AppleCare");
    // carrier iPhones show Continue (to the T-Mobile account check) instead of Add to Bag until the carrier is verified
    let bag, proceed;
    for (let i = 0; i < 20; i++) {
      // the AppleCare section can redraw after our click (seen in Safari) and drop the choice; pick it again
      if (!document.querySelector("input[name=applecare-options]:checked")) {
        const ac = shown("input[data-autom=noapplecare]");
        if (ac && !ac.disabled) ((ac.labels && ac.labels[0]) || ac).click();
      }
      bag = shown("button[data-autom=add-to-cart]"); proceed = shown("button[data-autom=proceed]");
      if ((bag && !bag.disabled) || (proceed && !proceed.disabled)) break;
      await sleep(500);
    }
    if (!ADD_TO_BAG) return status("ready - Apple Card, T-Mobile, no AppleCare selected (stopped before " + (bag ? "Add to Bag" : "Continue") + ")", "#248a3d");
    if (bag && !bag.disabled) { status("adding to bag - checkout continues on its own", "#248a3d"); bag.click(); }
    else if (proceed && !proceed.disabled) { status("continuing to T-Mobile", "#248a3d"); proceed.click(); }
    else throw new Error("neither Add to Bag nor Continue is enabled");
  } catch (e) {
    status("stopped: " + e.message + " - finish the choices by hand", "#d70015");
  }
})();
