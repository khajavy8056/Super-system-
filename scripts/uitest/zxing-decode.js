/* v1.8 — proves the vendored ZXing decodes a real EAN-13 raster the same way the mobile scanner feeds it
   (grayscale luminance → RGBLuminanceSource → HybridBinarizer → MultiFormatReader with TRY_HARDER). */
const fs = require("fs"); const path = require("path"); const { PNG } = require("pngjs");
const FE = path.join(__dirname, "..", "..", "frontend");
global.window = global; global.self = global; global.navigator = { userAgent: "node" };
const Z = require(FE + "/mobile/vendor/zxing.min.js");  // UMD → CommonJS in node, window.ZXing in the browser if (!Z) { console.log("FAIL ZXing global missing"); process.exit(1); }
const png = PNG.sync.read(fs.readFileSync(process.argv[2])); const { width: w, height: h, data } = png;
const lum = new Uint8ClampedArray(w * h); for (let i = 0, j = 0; j < w * h; i += 4, j++) lum[j] = (data[i] * 77 + data[i + 1] * 151 + data[i + 2] * 28) >> 8;
const hints = new Map(); hints.set(Z.DecodeHintType.TRY_HARDER, true); hints.set(Z.DecodeHintType.POSSIBLE_FORMATS, [Z.BarcodeFormat.EAN_13, Z.BarcodeFormat.CODE_128, Z.BarcodeFormat.QR_CODE]);
const r = new Z.MultiFormatReader(); r.setHints(hints);
const t0 = Date.now(); let res = null; const N = 20;
for (let k = 0; k < N; k++) { try { res = r.decode(new Z.BinaryBitmap(new Z.HybridBinarizer(new Z.RGBLuminanceSource(lum, w, h)))); } catch (e) { res = null; console.log("  miss:", e && e.constructor && e.constructor.kind); break; } r.reset(); }
const ms = (Date.now() - t0) / N;
const exp = process.argv[3];
console.log(`${res && res.getText() === exp ? "PASS" : "FAIL"} ZXing decoded ${res && res.getText()} (expected ${exp}) format=${res && Z.BarcodeFormat[res.getBarcodeFormat()]} ${w}x${h} avg ${ms.toFixed(1)} ms/frame`);
process.exit(res && res.getText() === exp ? 0 : 1);
