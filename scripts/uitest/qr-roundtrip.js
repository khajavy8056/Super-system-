/* Generates the pairing QR exactly like the desktop does (vendor-qrcode.js → SVG),
 * rasterises it and decodes with jsQR — proves the PC really shows a scannable code. */
const fs = require("fs"), path = require("path"), vm = require("vm");
const jsQR = require("jsqr");
const src = fs.readFileSync(path.join(__dirname, "..", "..", "frontend", "vendor-qrcode.js"), "utf8");
const sandbox = { module: { exports: {} }, exports: {}, window: {} }; vm.createContext(sandbox);
vm.runInContext(src, sandbox);
const qrcode = sandbox.module.exports || sandbox.qrcode || sandbox.window.qrcode;
const payload = { v: 1, url: "http://192.168.1.10:8000", urls: ["http://192.168.1.10:8000"], token: "eyJhbGciOiJIUzI1NiJ9." + "x".repeat(180), store: "سوپرمارکت خواجوی", device_id: "abc123def456" };
const text = "SMKT:" + Buffer.from(JSON.stringify(payload)).toString("base64url");
const q = qrcode(0, "M"); q.addData(text); q.make();
const n = q.getModuleCount(), cell = 4, margin = 8, size = n * cell + margin * 2;
const data = new Uint8ClampedArray(size * size * 4);
for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
  const mx = Math.floor((x - margin) / cell), my = Math.floor((y - margin) / cell);
  const dark = mx >= 0 && my >= 0 && mx < n && my < n && q.isDark(my, mx);
  const i = (y * size + x) * 4; data[i] = data[i + 1] = data[i + 2] = dark ? 0 : 255; data[i + 3] = 255;
}
const res = jsQR(data, size, size);
console.log("modules:", n, "text length:", text.length, "decoded:", !!res && res.data === text);
if (!res || res.data !== text) { console.log("QR ROUNDTRIP FAILED"); process.exit(1); }
const back = JSON.parse(Buffer.from(res.data.slice(5).replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf8"));
console.log("store:", back.store, "url:", back.url);
console.log("QR ROUNDTRIP OK");
