/* Shared dashboard behaviour: toasts, sortable tables, hold-to-delete,
   busy buttons, password toggle. No libraries. */
(function () {
  "use strict";

  const ICONS = {
    success: '<svg class="t-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.5 2.5L16 9.5"/></svg>',
    error: '<svg class="t-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5h.01"/></svg>',
    warn: '<svg class="t-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M12 3.5l9.5 16.5h-19z"/><path d="M12 10v4M12 17h.01"/></svg>',
  };
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /* ------------------------------------------------ toasts */
  const toaster = document.getElementById("toaster");

  function dismiss(el) {
    if (!el || el.classList.contains("is-leaving")) return;
    el.classList.add("is-leaving");
    const done = () => el.remove();
    el.addEventListener("transitionend", done, { once: true });
    setTimeout(done, 300); // fallback if transitions are disabled
  }

  function arm(el) {
    const close = el.querySelector(".toast-close");
    if (close) close.addEventListener("click", () => dismiss(el));
    const ms = Number(el.dataset.autodismiss || 0);
    if (!ms) return;
    // Pause the timer while hovered or while the tab is hidden
    let left = ms, started = Date.now(), timer = setTimeout(() => dismiss(el), left);
    const pause = () => { clearTimeout(timer); left -= Date.now() - started; };
    const resume = () => { started = Date.now(); clearTimeout(timer); timer = setTimeout(() => dismiss(el), Math.max(left, 800)); };
    el.addEventListener("mouseenter", pause);
    el.addEventListener("mouseleave", resume);
    document.addEventListener("visibilitychange", () => (document.hidden ? pause() : resume()));
  }

  function enter(el) {
    el.classList.add("is-entering");
    requestAnimationFrame(() => requestAnimationFrame(() => el.classList.remove("is-entering")));
  }

  /** toast({type, title, sub, html, autodismiss, id}) -> element */
  function toast(opts) {
    if (!toaster) return null;
    const type = opts.type || "success";
    if (opts.id) {
      const existing = toaster.querySelector(`[data-toast-id="${opts.id}"]`);
      if (existing) return existing;
    }
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.setAttribute("role", type === "error" ? "alert" : "status");
    if (opts.id) el.dataset.toastId = opts.id;
    const auto = opts.autodismiss ?? (type === "success" ? 3500 : 0);
    if (auto) el.dataset.autodismiss = auto;
    el.innerHTML = `${ICONS[type] || ICONS.success}
      <div class="t-body"><div class="t-title">${esc(opts.title)}</div>
        ${opts.sub ? `<div class="t-sub">${esc(opts.sub)}</div>` : ""}${opts.html || ""}</div>
      <button class="toast-close" type="button" aria-label="Dismiss">✕</button>`;
    toaster.appendChild(el);
    enter(el);
    arm(el);
    return el;
  }

  // Server-rendered flash messages become toasts
  document.querySelectorAll(".toast[data-server]").forEach(el => { enter(el); arm(el); });

  /* ------------------------------------------------ sortable tables */
  function cellValue(row, i) {
    const cell = row.cells[i];
    if (!cell) return "";
    const v = cell.dataset.sort ?? cell.textContent.trim();
    return v === "—" ? "" : v;
  }
  function compare(a, b) {
    if (a === "" && b !== "") return 1;           // blanks last
    if (b === "" && a !== "") return -1;
    const na = Number(a), nb = Number(b);
    if (a !== "" && b !== "" && !isNaN(na) && !isNaN(nb)) return na - nb;
    return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
  }
  document.querySelectorAll("table.sortable").forEach(table => {
    const ths = table.tHead ? [...table.tHead.rows[0].cells] : [];
    let col = 0;
    const colOf = new Map();                       // real column index (header cells may span columns)
    ths.forEach(th => { colOf.set(th, col); col += th.colSpan || 1; });
    ths.forEach(th => {
      const i = colOf.get(th);
      const visible = [...th.childNodes].filter(n => !(n.classList && n.classList.contains("sr-only")))
        .map(n => n.textContent).join("").trim();
      if (th.hasAttribute("data-nosort") || (th.colSpan || 1) > 1 || !visible) return;
      const label = th.textContent.trim();
      th.dataset.label = label;
      th.innerHTML = `<button type="button" class="sort-btn">${esc(label)}<span class="sr-only">, sort</span></button>`;
      th.querySelector("button").addEventListener("click", () => {
        const dir = th.getAttribute("aria-sort") === "ascending" ? "descending" : "ascending";
        ths.forEach(h => h.removeAttribute("aria-sort"));
        th.setAttribute("aria-sort", dir);
        const body = table.tBodies[0];
        const rows = [...body.rows].filter(r => !r.querySelector(".empty"));
        rows.sort((a, b) => compare(cellValue(a, i), cellValue(b, i)) * (dir === "ascending" ? 1 : -1));
        rows.forEach(r => body.appendChild(r));
      });
    });
  });

  /* ------------------------------------------------ hold-to-delete */
  const HOLD_MS = 1500;
  document.querySelectorAll("button.hold").forEach(btn => {
    let timer = null;
    const start = e => {
      if (timer || (e.type === "pointerdown" && e.button !== 0)) return;
      btn.classList.add("holding");
      timer = setTimeout(() => {
        timer = null;
        btn.setAttribute("aria-busy", "true");
        btn.closest("form").submit();
      }, HOLD_MS);
    };
    const cancel = () => {
      if (!timer) return;
      clearTimeout(timer); timer = null;
      btn.classList.remove("holding");
      toast({ type: "warn", title: "Keep holding to delete", sub: "Press and hold the button for 1.5 seconds.", autodismiss: 2500, id: "hold-hint" });
    };
    btn.addEventListener("pointerdown", e => { btn.setPointerCapture?.(e.pointerId); start(e); });
    btn.addEventListener("pointerup", cancel);
    btn.addEventListener("pointercancel", cancel);
    btn.addEventListener("keydown", e => { if ((e.key === " " || e.key === "Enter") && !e.repeat) { e.preventDefault(); start(e); } });
    btn.addEventListener("keyup", e => { if (e.key === " " || e.key === "Enter") cancel(); });
    btn.addEventListener("blur", cancel);
    btn.addEventListener("click", e => e.preventDefault());
  });

  /* ------------------------------------------------ busy submit buttons */
  document.querySelectorAll("form:not([data-undo])").forEach(form => {
    form.addEventListener("submit", () => {
      const btn = form.querySelector("button:not([type=button]):not(.hold)");
      if (btn) { setTimeout(() => { btn.disabled = true; btn.setAttribute("aria-busy", "true"); }, 0); }
    });
  });

  // Coming back with the browser Back button: re-enable buttons
  window.addEventListener("pageshow", e => {
    if (e.persisted) document.querySelectorAll("[aria-busy=true]").forEach(b => { b.disabled = false; b.removeAttribute("aria-busy"); });
  });

  /* ------------------------------------------------ password show/hide */
  document.querySelectorAll(".pw-toggle").forEach(b => {
    b.addEventListener("click", () => {
      const input = b.parentElement.querySelector("input");
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      b.textContent = show ? "Hide" : "Show";
      b.setAttribute("aria-pressed", String(show));
    });
  });

  const reduceMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ------------------------------------------------ numbers that count to their new value
     Starts from what's on screen right now, so a new update mid-count just re-targets. */
  function setNumber(el, value) {
    if (!el) return;
    const to = Number(value);
    const shown = Number(String(el.textContent).replace(/[^\d.-]/g, ""));
    if (!Number.isFinite(to) || !el.dataset.counted || !Number.isFinite(shown) || reduceMotion() || shown === to) {
      cancelAnimationFrame(el._raf); el.textContent = value; el.dataset.counted = "1"; return;
    }
    const from = shown, start = performance.now(), dur = Math.min(600, 250 + 25 * Math.abs(to - from));
    cancelAnimationFrame(el._raf);
    const step = now => {
      const t = Math.min(1, (now - start) / dur), e = 1 - Math.pow(1 - t, 3);   // ease-out, no overshoot
      el.textContent = Math.round(from + (to - from) * e);
      if (t < 1) el._raf = requestAnimationFrame(step);
    };
    el._raf = requestAnimationFrame(step);
  }

  /* ------------------------------------------------ dialogs grow out of the button that opened them */
  let lastPress = null;
  document.addEventListener("pointerdown", e => { lastPress = e.target.closest("button, a, [role=button]"); }, true);
  document.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") lastPress = document.activeElement; }, true);
  if (window.HTMLDialogElement) {
    const showModal = HTMLDialogElement.prototype.showModal;
    HTMLDialogElement.prototype.showModal = function () {
      const trigger = lastPress && document.contains(lastPress) ? lastPress : document.activeElement;
      showModal.call(this);
      if (!trigger || trigger === document.body) { this.style.transformOrigin = ""; return; }
      const t = trigger.getBoundingClientRect(), d = this.getBoundingClientRect();
      this.style.transformOrigin = `${t.left + t.width / 2 - d.left}px ${t.top + t.height / 2 - d.top}px`;
    };
  }

  /* ------------------------------------------------ delete now, undo for a few seconds
     <form data-undo="Message"> : the item disappears at once and the request is only sent
     when the Undo toast runs out (or the page is left). */
  const UNDO_MS = 7000;
  const pending = new Set();
  function commit(job) {
    if (!pending.delete(job)) return;
    clearTimeout(job.timer);
    dismiss(job.toast);
    fetch(job.form.action || location.href, { method: "POST", body: new FormData(job.form), credentials: "same-origin", keepalive: true })
      .then(r => {
        if (!r.ok) throw new Error(r.status);
        job.item.remove();
        document.dispatchEvent(new CustomEvent("undo-committed", { detail: job.form }));
      })
      .catch(() => { restore(job); toast({ type: "error", title: "Couldn't delete that", sub: "Check that the app is still running, then try again." }); });
  }
  function restore(job) {
    job.item.hidden = false;
    job.item.classList.add("is-restoring");
    requestAnimationFrame(() => requestAnimationFrame(() => job.item.classList.remove("is-restoring")));
  }
  document.querySelectorAll("form[data-undo]").forEach(form => {
    form.addEventListener("submit", e => {
      e.preventDefault();
      e.stopImmediatePropagation();
      const item = form.closest("[data-undo-item], li, tr") || form;
      const job = { form, item };
      item.hidden = true;
      job.toast = toast({ type: "success", autodismiss: 0, title: form.dataset.undo,
        html: `<div class="t-actions"><button type="button" class="btn sm secondary undo-btn">Undo</button></div>` });
      job.toast.querySelector(".undo-btn").addEventListener("click", () => {
        pending.delete(job); clearTimeout(job.timer); dismiss(job.toast); restore(job);
        const again = form.querySelector("button"); if (again) again.focus();
      });
      job.toast.querySelector(".toast-close").addEventListener("click", () => commit(job));
      job.timer = setTimeout(() => commit(job), UNDO_MS);
      pending.add(job);
      const next = item.nextElementSibling?.querySelector("button, a") || item.previousElementSibling?.querySelector("button, a");
      if (next) next.focus({ preventScroll: true });
    }, true);
  });
  window.addEventListener("pagehide", () => [...pending].forEach(commit));

  /* ------------------------------------------------ sticky table headers: show the soft edge only when content is under them */
  if ("IntersectionObserver" in window) {
    document.querySelectorAll(".table-wrap.sticky-head").forEach(wrap => {
      const sentinel = document.createElement("div");
      sentinel.className = "sticky-sentinel"; sentinel.setAttribute("aria-hidden", "true");
      wrap.before(sentinel);
      new IntersectionObserver(([e]) => wrap.classList.toggle("is-stuck", !e.isIntersecting && e.boundingClientRect.top < 0))
        .observe(sentinel);
    });
  }

  /* ------------------------------------------------ stale-data watcher */
  /* Pages that poll call watch(); ok() after every good refresh, fail() after a bad one.
     If nothing has succeeded for STALE_MS, a banner says the numbers are old and since when. */
  function watch() {
    const STALE_MS = 10000;
    const main = document.getElementById("main");
    if (!main) return { ok() {}, fail() {} };
    const bar = document.createElement("div");
    bar.className = "stale-bar";
    bar.setAttribute("role", "status");
    bar.hidden = true;
    main.insertBefore(bar, main.firstChild);
    let lastOk = Date.now();
    const clock = d => d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
    function paint() {
      const stale = !document.hidden && Date.now() - lastOk > STALE_MS;
      bar.hidden = !stale;
      if (!stale) return;
      const msg = `Connection lost. These numbers are from ${clock(new Date(lastOk))}. Trying again\u2026`;
      if (bar.textContent !== msg) bar.textContent = msg;   // only re-announce when the message changes
    }
    setInterval(paint, 1000);
    return { ok() { lastOk = Date.now(); paint(); }, fail() { paint(); } };
  }

  window.ui = { toast, dismiss, esc, setNumber, reduceMotion, watch };
})();
