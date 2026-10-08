/* Build 495 — browser-level smoke test for the four permission-derived dashboard profiles.
 * Requires the local FastAPI app (default http://127.0.0.1:8000) and jsdom. */
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");
const BASE = process.env.SMOKE_BASE || "http://127.0.0.1:8000";
const FE = path.join(__dirname, "..", "..", "frontend");
const password = "pass1234";

async function request(route, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.token) headers.Authorization = `Bearer ${options.token}`;
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  return fetch(new URL(route, BASE), { ...options, headers });
}

async function createAccount(adminToken, profile, role, permissions = []) {
  const username = `smoke495_${profile}_${Date.now()}_${Math.floor(Math.random() * 10000)}`;
  const response = await request("/api/users", {
    method: "POST", token: adminToken,
    body: JSON.stringify({ username, password, full_name: `${profile} user`, roles: role ? [role] : [], permissions, local_only: false }),
  });
  if (response.status !== 201) throw new Error(`create ${profile} user failed: ${response.status} ${await response.text()}`);
  const login = await request("/api/auth/login", {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username, password }),
  });
  if (!login.ok) throw new Error(`login ${profile} failed: ${login.status} ${await login.text()}`);
  return (await login.json()).access_token;
}

async function renderWithToken(token) {
  const html = fs.readFileSync(path.join(FE, "index.html"), "utf8");
  const dom = new JSDOM(html, { url: `${BASE}/`, runScripts: "outside-only", pretendToBeVisual: true });
  const { window } = dom;
  window.fetch = (input, init) => {
    const url = typeof input === "string" && input.startsWith("http") ? input : new URL(input, BASE).href;
    return fetch(url, init);
  };
  window.matchMedia = window.matchMedia || (() => ({ matches: false, addEventListener() {}, addListener() {} }));
  window.navigator.serviceWorker = { register: async () => {} };
  window.localStorage.setItem("token", token);
  window.eval(fs.readFileSync(path.join(FE, "jalali.js"), "utf8"));
  window.eval(fs.readFileSync(path.join(FE, "app.js"), "utf8"));
  await new Promise((resolve) => setTimeout(resolve, 2200));
  await window.go("dashboard");
  await new Promise((resolve) => setTimeout(resolve, 500));
  return { dom, window };
}

(async () => {
  const adminLogin = await request("/api/auth/login", {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username: "admin", password: "admin123" }),
  });
  if (!adminLogin.ok) throw new Error(`admin login failed: ${adminLogin.status} ${await adminLogin.text()}`);
  const adminToken = (await adminLogin.json()).access_token;
  const profiles = [
    { profile: "seller", role: "Cashier", selector: ".role-dashboard--seller", title: "پنل فروش و صندوق" },
    { profile: "accountant", role: "Accountant", selector: ".role-dashboard--accountant", title: "پنل حسابداری" },
    { profile: "supervisor", role: "Supervisor", selector: ".dashboard-profile--supervisor", title: "پنل سوپروایزر" },
  ];
  for (const test of profiles) {
    const token = await createAccount(adminToken, test.profile, test.role);
    const { dom, window } = await renderWithToken(token);
    const view = window.document.getElementById("view");
    if (!view.matches(test.selector) && !view.querySelector(test.selector)) throw new Error(`${test.profile}: expected dashboard ${test.selector}`);
    if (window.document.getElementById("view-title").textContent !== test.title) throw new Error(`${test.profile}: wrong page title`);
    if (window.document.querySelector("#view p.error")) throw new Error(`${test.profile}: dashboard rendered an error`);
    if (test.profile === "seller" && view.querySelector(".role-action[onclick*=users],.role-action[onclick*=settings],.role-action[onclick*=accounting]")) {
      throw new Error("seller: a management/financial shortcut leaked into the panel");
    }
    if (test.profile === "accountant" && view.querySelector(".role-action[onclick*=pos]")) {
      throw new Error("accountant: POS shortcut shown without pos.sell");
    }
    console.log(`${test.profile.padEnd(11)} dashboard rendered with title "${test.title}"`);
    window.close(); dom.window.close();
  }
  const financeOnlyToken = await createAccount(adminToken, "finance_only", null, ["reports.view", "accounting.view"]);
  const financeOnly = await renderWithToken(financeOnlyToken);
  if (!financeOnly.window.document.querySelector("#view .role-dashboard--accountant")) {
    throw new Error("accounting.view without reports.view_all: expected the accountant dashboard");
  }
  if (financeOnly.window.document.querySelector("#view .role-summary-list,#view .role-invoices")) {
    throw new Error("accounting.view without reports.view_all: store sales or invoices leaked into the dashboard");
  }
  console.log("accounting-only  financial dashboard rendered without store sales or invoices");
  financeOnly.window.close();

  const adminDom = await renderWithToken(adminToken);
  if (!adminDom.window.document.querySelector("#view.dashboard-profile--administrator .og-grid")) {
    throw new Error("administrator: expected the supervisor-style management dashboard");
  }
  console.log("administrator dashboard rendered with the management layout");
  adminDom.window.close();
  console.log("ALL FOUR DASHBOARD PROFILES PASSED");
})().catch((error) => { console.error(error); process.exit(1); });
