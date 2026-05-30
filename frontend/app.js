// Sikok customer mobile web app
// Talks to the FastAPI backend (REST + Socket.IO) on the same origin.

const API = ""; // same-origin via Nginx; override for dev with e.g. "http://localhost:8000"
const SHOP_ID = Number(new URLSearchParams(location.search).get("shop") || 1);
const STAMPS_TOTAL = 4;

const $ = (id) => document.getElementById(id);
const els = {
  shopName: $("shop-name"),
  shopSub: $("shop-sub"),
  shopAddr: $("shop-addr"),
  wa: $("wa-link"),
  map: $("map-link"),
  authCard: $("auth-card"),
  dashCard: $("dash-card"),
  form: $("auth-form"),
  mobile: $("mobile"),
  password: $("password"),
  name: $("name"),
  nameRow: $("name-row"),
  submit: $("auth-submit"),
  err: $("auth-err"),
  forgot: $("forgot-link"),
  userName: $("user-name"),
  lastVisit: $("last-visit"),
  stamps: $("stamps"),
  progress: $("progress"),
  request: $("request-btn"),
  status: $("status"),
  logout: $("logout"),
};

const store = {
  get token() { return localStorage.getItem("sikok.token"); },
  set token(v) { v ? localStorage.setItem("sikok.token", v) : localStorage.removeItem("sikok.token"); },
  get user() { try { return JSON.parse(localStorage.getItem("sikok.user") || "null"); } catch { return null; } },
  set user(v) { v ? localStorage.setItem("sikok.user", JSON.stringify(v)) : localStorage.removeItem("sikok.user"); },
};

async function api(path, { method = "GET", body, auth = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth && store.token) headers.Authorization = `Bearer ${store.token}`;
  const res = await fetch(`${API}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const txt = await res.text();
  const data = txt ? JSON.parse(txt) : null;
  if (!res.ok) {
    const err = new Error(data?.detail || res.statusText);
    err.status = res.status;
    err.detail = data?.detail;
    throw err;
  }
  return data;
}

// ---------------------------------------------------------------------------
// Shop header
// ---------------------------------------------------------------------------

async function loadShop() {
  try {
    const shop = await api(`/api/shops/${SHOP_ID}`);
    els.shopName.textContent = shop.name || "Sikok";
    els.shopSub.textContent = shop.sub_name || "";
    els.shopAddr.textContent = shop.address || "";
    if (shop.whatsapp_url) els.wa.href = shop.whatsapp_url;
    if (shop.maps_url) els.map.href = shop.maps_url;
  } catch (e) {
    els.shopName.textContent = "Sikok";
    els.shopAddr.textContent = "Could not load shop info.";
  }
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

function showError(msg) {
  els.err.textContent = msg;
  els.err.hidden = !msg;
}

els.mobile.addEventListener("blur", () => { showError(""); els.nameRow.hidden = true; });

els.form.addEventListener("submit", async (e) => {
  e.preventDefault();
  showError("");
  els.submit.disabled = true;
  try {
    const payload = {
      mobile_number: els.mobile.value.trim(),
      password: els.password.value,
    };
    if (!els.nameRow.hidden && els.name.value.trim()) payload.name = els.name.value.trim();

    const res = await api("/api/auth/login", { method: "POST", body: payload });
    store.token = res.token;
    store.user = { user_id: res.user_id, name: res.name, mobile_number: res.mobile_number };
    await enterDashboard();
  } catch (err) {
    if (err.detail === "NEW_USER_NAME_REQUIRED") {
      els.nameRow.hidden = false;
      els.name.focus();
      showError("New here — please tell us your name.");
    } else {
      showError(err.detail || err.message || "Something went wrong.");
    }
  } finally {
    els.submit.disabled = false;
  }
});

els.forgot.addEventListener("click", async () => {
  showError("");
  const mobile = els.mobile.value.trim();
  if (!mobile) { showError("Enter your mobile number first."); return; }
  try {
    await api("/api/auth/forgot-password", {
      method: "POST",
      body: { mobile_number: mobile },
    });
    setStatus("Reset request sent. Ask the counter for your PIN, then sign in.", "wait");
  } catch (err) {
    showError(err.detail || "Could not send reset request.");
  }
});

els.logout.addEventListener("click", () => {
  store.token = null;
  store.user = null;
  location.reload();
});

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

function renderStamps(filled) {
  els.stamps.innerHTML = "";
  for (let i = 0; i < STAMPS_TOTAL; i++) {
    const slot = document.createElement("div");
    slot.className = "stamp";
    if (i < filled) {
      slot.classList.add("filled");
      slot.textContent = "★";
    } else {
      slot.textContent = (i + 1).toString();
    }
    els.stamps.appendChild(slot);
  }
  const remaining = Math.max(0, STAMPS_TOTAL - filled);
  els.progress.textContent =
    filled >= STAMPS_TOTAL - 1
      ? "Your next visit unlocks ₹100 off per item."
      : `${remaining} more visit${remaining === 1 ? "" : "s"} until your reward.`;
}

function setStatus(text, kind = "") {
  els.status.textContent = text || "";
  els.status.className = "status" + (kind ? " " + kind : "");
}

let cachedCard = null;

async function loadCard() {
  const card = await api(`/api/me/card?shop_id=${SHOP_ID}`, { auth: true });
  cachedCard = card;
  renderStamps(card.current_stamps);
  if (card.last_visit_ist) {
    els.lastVisit.textContent = `Last visit: ${card.last_visit_ist}`;
  } else {
    els.lastVisit.textContent = "No visits yet — scan your first stamp today.";
  }
  if (card.stamped_today) {
    els.request.disabled = true;
    setStatus("Today's stamp is already collected. See you tomorrow!", "ok");
  } else {
    els.request.disabled = false;
    setStatus("");
  }
  return card;
}

async function enterDashboard() {
  els.authCard.hidden = true;
  els.dashCard.hidden = false;
  els.userName.textContent = store.user?.name || "";
  await loadCard();
}

// ---------------------------------------------------------------------------
// Stamp request flow
// ---------------------------------------------------------------------------

let waitingSocket = null;

els.request.addEventListener("click", async () => {
  if (cachedCard?.stamped_today) {
    setStatus("Today's stamp is already collected. See you tomorrow!", "ok");
    return;
  }
  els.request.disabled = true;
  setStatus("Sending request to the counter…", "wait");
  try {
    const res = await api("/api/stamps/request", {
      method: "POST",
      body: { shop_id: SHOP_ID },
      auth: true,
    });
    setStatus("Waiting for Counter Approval…", "wait");
    await openSocket(res.pending_id);
  } catch (err) {
    if (err.status === 409) {
      setStatus(err.detail || "Today's stamp is already collected.", "ok");
      await loadCard();
    } else {
      setStatus(err.detail || "Request failed.", "err");
      els.request.disabled = false;
    }
  }
});

async function openSocket(pendingId) {
  if (waitingSocket) { try { waitingSocket.disconnect(); } catch {} }
  waitingSocket = io({
    path: "/socket.io",
    transports: ["websocket", "polling"],
    auth: { token: store.token, pending_id: pendingId },
  });

  const finish = ({ keepDisabled = false } = {}) => {
    try { waitingSocket?.disconnect(); } catch {}
    waitingSocket = null;
    if (!keepDisabled) els.request.disabled = false;
  };

  waitingSocket.on("connect_error", () => {
    setStatus("Connection lost. Try again.", "err");
    finish();
  });

  waitingSocket.on("stamp_approved", async (payload) => {
    const reward = payload?.discount_applied;
    await loadCard();  // refreshes button state via stamped_today
    setStatus(
      reward
        ? `Reward applied! Sale logged: ₹${payload.sale_amount}. Card reset.`
        : `Stamp added! Sale logged: ₹${payload.sale_amount}.`,
      "ok"
    );
    finish({ keepDisabled: true });
  });

  waitingSocket.on("stamp_declined", (payload) => {
    setStatus(payload?.reason || "Declined by Counter", "err");
    finish();
  });

  waitingSocket.on("password_reset", () => {
    setStatus("✅ Reset approved — ask the counter for your PIN.", "ok");
    finish();
  });
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

(async function boot() {
  await loadShop();
  if (store.token && store.user) {
    try { await enterDashboard(); return; }
    catch { store.token = null; store.user = null; }
  }
})();
