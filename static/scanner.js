/* USB keyboard-type RFID reader support.
   These readers act like a keyboard: they "type" the card number very fast and press Enter.
   We tell a reader apart from a person by speed: a reader types each character within a few
   milliseconds, a person takes 100 ms or more. */
(function () {
  "use strict";
  const mode = document.body.dataset.readerMode;
  if (mode !== "keyboard" && mode !== "both") return;

  const MAX_GAP_MS = 80;     // max pause between characters from the reader
  const MIN_LENGTH = 4;      // shortest card number we accept

  let buffer = "", times = [];

  const isEditable = el => el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));

  function reset() { buffer = ""; times = []; }

  function looksLikeReader() {
    if (buffer.length < MIN_LENGTH) return false;
    for (let i = 1; i < times.length; i++) if (times[i] - times[i - 1] > MAX_GAP_MS) return false;
    return Date.now() - times[times.length - 1] <= MAX_GAP_MS * 2;
  }

  async function record(uid) {
    // A page can take over the scan (e.g. the Add student form just fills in the UID)
    if (typeof window.onRfidScan === "function") { window.onRfidScan(uid); return; }
    try {
      const res = await fetch("/api/scan", {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({uid}),
      });
      if (res.status === 401) { location.href = "/login"; return; }
      const r = await res.json();
      document.dispatchEvent(new CustomEvent("rfid-result", {detail: r}));
      if (window.ui && !document.body.dataset.kiosk && !window.SKIP_SCAN_TOAST) notify(r);
    } catch (e) {
      window.ui?.toast({type: "error", title: "Couldn't record the tap", sub: "Is the attendance app still running?"});
    }
  }

  function notify(r) {
    const name = r.name || "";
    switch (r.result) {
      case "AM_IN": case "PM_IN":
        return ui.toast({type: "success", title: `${r.label}: ${name}`, sub: r.status === "LATE" ? "Late" : "On time"});
      case "AM_OUT": case "PM_OUT":
        return ui.toast({type: "success", title: `${r.label}: ${name}`});
      case "DUP":  return ui.toast({type: "warn", title: `${name}: repeat tap ignored`, autodismiss: 3000});
      case "DONE": return ui.toast({type: "warn", title: `${name} already logged out`, autodismiss: 3000});
      default:
        return ui.toast({type: "warn", id: "card-" + r.uid, autodismiss: 0, title: "Unregistered card tapped", sub: `Card ${r.uid}`,
          html: `<div class="t-actions"><a class="btn sm" href="/students/new?uid=${encodeURIComponent(r.uid)}">Register this card</a></div>`});
    }
  }

  document.addEventListener("keydown", e => {
    if (e.ctrlKey || e.altKey || e.metaKey) return;
    const target = e.target;
    const rfidField = target && target.matches && target.matches("[data-rfid-target]");
    // Typing in a normal form field: leave it alone (the reader may also type there on purpose)
    if (isEditable(target) && !rfidField) { reset(); return; }

    const now = Date.now();
    if (e.key === "Enter" || e.key === "Tab") {
      if (looksLikeReader()) {
        e.preventDefault();
        const uid = buffer.toUpperCase();
        if (rfidField) {                       // scanned straight into the UID box
          target.value = uid;
          target.dispatchEvent(new Event("input", {bubbles: true}));
          window.ui?.toast({type: "success", title: "Card read", sub: uid, autodismiss: 2500, id: "card-read"});
        } else {
          record(uid);
        }
      } else if (rfidField && e.key === "Enter") {
        e.preventDefault();                    // never submit the form from the UID box
      }
      reset();
      return;
    }
    if (e.key.length !== 1 || !/[0-9a-zA-Z]/.test(e.key)) { reset(); return; }
    if (times.length && now - times[times.length - 1] > MAX_GAP_MS) reset();
    buffer += e.key;
    times.push(now);
  }, true);
})();
