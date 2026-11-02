// Pre-fills the iPhone Duo buy page: Finance -> Apple Card Monthly Installments -> T-Mobile -> No AppleCare -> Add to Bag.
// Never checks out. Run inside the buy page (duo_watch.py injects it into Chrome via AppleScript).
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
  async function pick(sel, name) {
    for (let i = 0; i < 40; i++) {                 // ~20s: later sections stay disabled until earlier ones are answered
      const el = shown(sel);
      if (el && el.checked) return;
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

  try {
    status("choosing Finance...");
    // the page remembers earlier choices; reopen the payment section unless it already says Apple Card
    if (summary() && !/Apple Card Monthly/i.test(summary().closest("div").parentElement.textContent)) { summary().click(); await sleep(800); }
    if (!(summary() && /Apple Card Monthly/i.test(summary().closest("div").parentElement.textContent))) {
      await pick("input[name=purchase_option_group][value=finance]", "Finance");
      status("choosing Apple Card Monthly Installments...");
      await pick("input[data-autom=purchaseOptionbfi]", "Apple Card Monthly Installments");
      await sleep(2000);                            // payment section collapses, then carriers re-enable
    }
    status("choosing T-Mobile...");                 // choosing Finance clears the carrier
    await pick("input[name=carrierModel][value=TMOBILE_IPHONEDUO]", "T-Mobile");
    status("choosing No AppleCare...");
    await pick("input[data-autom=noapplecare]", "No AppleCare");
    const bag = document.querySelector("button[data-autom=add-to-cart]");
    for (let i = 0; i < 20 && bag && bag.disabled; i++) await sleep(500);
    if (!ADD_TO_BAG) return status("ready - Apple Card, T-Mobile, no AppleCare selected (stopped before Add to Bag)", "#248a3d");
    if (!bag || bag.disabled) throw new Error("Add to Bag is not enabled");
    status("adding to bag - then choose Pickup at the store from the alert and check out yourself", "#248a3d");
    bag.click();
  } catch (e) {
    status("stopped: " + e.message + " - finish the choices by hand", "#d70015");
  }
})();
