package ir.khajavy.supermarket;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.ImageFormat;
import android.graphics.Paint;
import android.graphics.SurfaceTexture;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.Image;
import android.media.ImageReader;
import android.media.ToneGenerator;
import android.media.AudioManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Vibrator;
import android.util.Size;
import android.view.Gravity;
import android.view.Surface;
import android.view.TextureView;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import com.google.zxing.BarcodeFormat;
import com.google.zxing.BinaryBitmap;
import com.google.zxing.DecodeHintType;
import com.google.zxing.MultiFormatReader;
import com.google.zxing.PlanarYUVLuminanceSource;
import com.google.zxing.ReaderException;
import com.google.zxing.Result;
import com.google.zxing.common.HybridBinarizer;

import java.nio.ByteBuffer;
import java.util.Arrays;
import java.util.EnumMap;
import java.util.EnumSet;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * v1.8.1 — NATIVE barcode scanner (Camera2 + ZXing core, no WebView/getUserMedia).
 *
 * Why: WebView camera access is slow and unreliable on many Android builds
 * (no BarcodeDetector, low-res getUserMedia, no continuous autofocus). This
 * activity decodes the Y plane of every preview frame (~30 fps) with ZXing,
 * restricted to a central band, with continuous AF, torch and haptic/beep.
 *
 * Result: {@code Intent.putExtra("code", text)} + {@code "format"}; RESULT_CANCELED on back.
 */
public class ScanActivity extends Activity implements TextureView.SurfaceTextureListener {
    public static final String EXTRA_CODE = "code";
    public static final String EXTRA_FORMAT = "format";
    public static final String EXTRA_TITLE = "title";

    private TextureView preview;
    private TextView status;
    private Button torchBtn;
    private CameraDevice camera;
    private CameraCaptureSession session;
    private CaptureRequest.Builder requestBuilder;
    private ImageReader reader;
    private HandlerThread thread;
    private Handler handler;
    private String cameraId;
    private Size previewSize = new Size(1280, 720);
    private boolean torch = false;
    private boolean torchAvailable = false;
    private final AtomicBoolean done = new AtomicBoolean(false);
    private final AtomicBoolean busy = new AtomicBoolean(false);
    private MultiFormatReader zx;
    private int sensorOrientation = 90;
    private long lastMiss = 0;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        getWindow().setStatusBarColor(Color.BLACK);

        zx = new MultiFormatReader();
        Map<DecodeHintType, Object> hints = new EnumMap<>(DecodeHintType.class);
        hints.put(DecodeHintType.TRY_HARDER, Boolean.TRUE);
        hints.put(DecodeHintType.POSSIBLE_FORMATS, EnumSet.of(BarcodeFormat.EAN_13, BarcodeFormat.EAN_8, BarcodeFormat.UPC_A, BarcodeFormat.UPC_E,
                BarcodeFormat.CODE_128, BarcodeFormat.CODE_39, BarcodeFormat.CODE_93, BarcodeFormat.ITF, BarcodeFormat.CODABAR,
                BarcodeFormat.QR_CODE, BarcodeFormat.DATA_MATRIX));
        zx.setHints(hints);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        preview = new TextureView(this);
        preview.setSurfaceTextureListener(this);
        root.addView(preview, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        // viewfinder frame (central band = decode region)
        View frame = new View(this) {
            final Paint p = new Paint();
            @Override protected void onDraw(android.graphics.Canvas c) {
                int w = getWidth(), h = getHeight();
                p.setColor(0x88000000); p.setStyle(Paint.Style.FILL);
                int top = (int) (h * 0.30f), bot = (int) (h * 0.70f);
                c.drawRect(0, 0, w, top, p); c.drawRect(0, bot, w, h, p);
                p.setColor(0xFF37B8AA); p.setStyle(Paint.Style.STROKE); p.setStrokeWidth(6);
                c.drawRoundRect(24, top, w - 24, bot, 18, 18, p);
                p.setColor(0xCCFF5252); p.setStrokeWidth(3);
                c.drawLine(40, h / 2f, w - 40, h / 2f, p);
            }
        };
        root.addView(frame, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        LinearLayout top = new LinearLayout(this);
        top.setOrientation(LinearLayout.VERTICAL);
        top.setPadding(32, 48, 32, 16);
        TextView title = new TextView(this);
        String t = getIntent().getStringExtra(EXTRA_TITLE);
        title.setText(t == null || t.isEmpty() ? "اسکن بارکد" : t);
        title.setTextColor(Color.WHITE); title.setTextSize(20); title.setGravity(Gravity.CENTER);
        status = new TextView(this);
        status.setText("دوربین را روی بارکد بگیرید");
        status.setTextColor(0xFFDDDDDD); status.setTextSize(14); status.setGravity(Gravity.CENTER);
        top.addView(title); top.addView(status);
        root.addView(top, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.TOP));

        LinearLayout bottom = new LinearLayout(this);
        bottom.setOrientation(LinearLayout.HORIZONTAL);
        bottom.setGravity(Gravity.CENTER);
        bottom.setPadding(24, 16, 24, 64);
        torchBtn = new Button(this);
        torchBtn.setText("چراغ‌قوه");
        torchBtn.setOnClickListener(v -> toggleTorch());
        Button cancel = new Button(this);
        cancel.setText("انصراف");
        cancel.setOnClickListener(v -> { setResult(RESULT_CANCELED); finish(); });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        lp.setMargins(12, 0, 12, 0);
        bottom.addView(torchBtn, lp); bottom.addView(cancel, lp);
        root.addView(bottom, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM));
        setContentView(root);
    }

    @Override protected void onResume() {
        super.onResume();
        thread = new HandlerThread("scan-cam"); thread.start(); handler = new Handler(thread.getLooper());
        if (preview.isAvailable()) openCamera();
    }

    @Override protected void onPause() {
        closeCamera();
        if (thread != null) { thread.quitSafely(); thread = null; handler = null; }
        super.onPause();
    }

    /* ---------------- camera ---------------- */
    private void openCamera() {
        CameraManager cm = (CameraManager) getSystemService(Context.CAMERA_SERVICE);
        try {
            for (String id : cm.getCameraIdList()) {
                CameraCharacteristics ch = cm.getCameraCharacteristics(id);
                Integer facing = ch.get(CameraCharacteristics.LENS_FACING);
                if (facing != null && facing == CameraCharacteristics.LENS_FACING_BACK) { cameraId = id; }
                if (cameraId != null) {
                    Boolean flash = ch.get(CameraCharacteristics.FLASH_INFO_AVAILABLE);
                    torchAvailable = flash != null && flash;
                    Integer so = ch.get(CameraCharacteristics.SENSOR_ORIENTATION);
                    if (so != null) sensorOrientation = so;
                    StreamConfigurationMap map = ch.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
                    if (map != null) previewSize = pick(map.getOutputSizes(ImageFormat.YUV_420_888));
                    break;
                }
            }
            if (cameraId == null) { status.setText("دوربین پشت پیدا نشد"); return; }
            runOnUiThread(() -> torchBtn.setVisibility(torchAvailable ? View.VISIBLE : View.GONE));
            if (checkSelfPermission(android.Manifest.permission.CAMERA) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{android.Manifest.permission.CAMERA}, 21); return;
            }
            reader = ImageReader.newInstance(previewSize.getWidth(), previewSize.getHeight(), ImageFormat.YUV_420_888, 2);
            reader.setOnImageAvailableListener(this::onFrame, handler);
            cm.openCamera(cameraId, new CameraDevice.StateCallback() {
                @Override public void onOpened(CameraDevice cd) { camera = cd; startSession(); }
                @Override public void onDisconnected(CameraDevice cd) { cd.close(); camera = null; }
                @Override public void onError(CameraDevice cd, int error) { cd.close(); camera = null; runOnUiThread(() -> status.setText("خطای دوربین (" + error + ")")); }
            }, handler);
        } catch (CameraAccessException | SecurityException e) {
            status.setText("دسترسی به دوربین ممکن نیست");
        }
    }

    @Override public void onRequestPermissionsResult(int code, String[] perms, int[] res) {
        super.onRequestPermissionsResult(code, perms, res);
        if (code == 21) { if (res.length > 0 && res[0] == android.content.pm.PackageManager.PERMISSION_GRANTED) openCamera(); else { status.setText("اجازهٔ دوربین داده نشد"); } }
    }

    private static Size pick(Size[] sizes) {
        if (sizes == null || sizes.length == 0) return new Size(1280, 720);
        Size best = sizes[0]; long bestScore = Long.MAX_VALUE;
        for (Size s : sizes) {
            long px = (long) s.getWidth() * s.getHeight();
            long score = Math.abs(px - 1280L * 720L);
            if (score < bestScore) { bestScore = score; best = s; }
        }
        return best;
    }

    private void startSession() {
        try {
            SurfaceTexture st = preview.getSurfaceTexture();
            st.setDefaultBufferSize(previewSize.getWidth(), previewSize.getHeight());
            Surface surf = new Surface(st);
            requestBuilder = camera.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
            requestBuilder.addTarget(surf);
            requestBuilder.addTarget(reader.getSurface());
            requestBuilder.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE);
            requestBuilder.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON);
            camera.createCaptureSession(Arrays.asList(surf, reader.getSurface()), new CameraCaptureSession.StateCallback() {
                @Override public void onConfigured(CameraCaptureSession s) {
                    session = s;
                    try { s.setRepeatingRequest(requestBuilder.build(), null, handler); } catch (CameraAccessException ignored) {}
                }
                @Override public void onConfigureFailed(CameraCaptureSession s) { runOnUiThread(() -> status.setText("پیکربندی دوربین ناموفق بود")); }
            }, handler);
        } catch (CameraAccessException e) {
            runOnUiThread(() -> status.setText("دسترسی به دوربین ممکن نیست"));
        }
    }

    private void toggleTorch() {
        if (requestBuilder == null || session == null) return;
        torch = !torch;
        requestBuilder.set(CaptureRequest.FLASH_MODE, torch ? CaptureRequest.FLASH_MODE_TORCH : CaptureRequest.FLASH_MODE_OFF);
        try { session.setRepeatingRequest(requestBuilder.build(), null, handler); } catch (CameraAccessException ignored) {}
        torchBtn.setText(torch ? "خاموش کردن چراغ" : "چراغ‌قوه");
    }

    private void closeCamera() {
        if (session != null) { session.close(); session = null; }
        if (camera != null) { camera.close(); camera = null; }
        if (reader != null) { reader.close(); reader = null; }
    }

    /* ---------------- decode ---------------- */
    private void onFrame(ImageReader r) {
        Image img = r.acquireLatestImage();
        if (img == null) return;
        if (done.get() || !busy.compareAndSet(false, true)) { img.close(); return; }
        try {
            Image.Plane y = img.getPlanes()[0];
            ByteBuffer buf = y.getBuffer();
            int w = img.getWidth(), h = img.getHeight(), stride = y.getRowStride();
            byte[] data = new byte[stride * h];
            buf.get(data, 0, Math.min(buf.remaining(), data.length));
            img.close(); img = null;
            // sensor is landscape (90°); the on-screen central band = central columns of the sensor image
            boolean portrait = sensorOrientation == 90 || sensorOrientation == 270;
            Result res = null;
            if (portrait) {
                byte[] rot = rotate90(data, stride, h);              // → width=h, height=w
                int rw = h, rh = w;
                int top = (int) (rh * 0.30f), bh = (int) (rh * 0.40f);
                res = decode(rot, rw, rh, 0, top, rw, bh);                                       // barcode horizontal on screen
                if (res == null) res = decode(data, stride, h, 0, (int) (h * 0.30f), stride, (int) (h * 0.40f)); // phone/barcode turned 90°
                if (res == null) res = decode(rot, rw, rh, 0, 0, rw, rh);                        // full frame (QR off-centre)
            } else {
                int top = (int) (h * 0.30f), bh = (int) (h * 0.40f);
                res = decode(data, stride, h, 0, top, stride, bh);
                if (res == null) res = decode(data, stride, h, 0, 0, stride, h);
            }
            if (res != null && res.getText() != null && !res.getText().isEmpty()) {
                String text = res.getText().trim();
                if (isNumericRetail(text) && !checksumOk(text)) { hint("بارکد ناقص خوانده شد — کمی نزدیک‌تر"); return; }
                if (done.compareAndSet(false, true)) deliver(text, res.getBarcodeFormat().name());
            } else if (System.currentTimeMillis() - lastMiss > 4000) {
                lastMiss = System.currentTimeMillis();
            }
        } finally {
            if (img != null) img.close();
            busy.set(false);
        }
    }

    private Result decode(byte[] yuv, int w, int h, int left, int top, int cw, int chh) {
        try {
            PlanarYUVLuminanceSource src = new PlanarYUVLuminanceSource(yuv, w, h, left, top, cw, chh, false);
            try { return zx.decodeWithState(new BinaryBitmap(new HybridBinarizer(src))); }
            catch (ReaderException e) { zx.reset(); return zx.decodeWithState(new BinaryBitmap(new HybridBinarizer(src.invert()))); }
        } catch (ReaderException | IllegalArgumentException e) {
            return null;
        } finally { zx.reset(); }
    }

    private static byte[] rotate90(byte[] src, int w, int h) {
        byte[] out = new byte[w * h];
        for (int y = 0; y < h; y++) {
            int row = y * w;
            for (int x = 0; x < w; x++) out[x * h + (h - 1 - y)] = src[row + x];
        }
        return out;
    }

    private static boolean isNumericRetail(String s) { return s.matches("\\d{8}|\\d{12}|\\d{13}"); }

    /** EAN-8 / UPC-A / EAN-13 mod-10 check digit. */
    public static boolean checksumOk(String s) {
        int sum = 0, n = s.length();
        for (int i = 0; i < n - 1; i++) {
            int d = s.charAt(n - 2 - i) - '0';
            sum += (i % 2 == 0) ? d * 3 : d;
        }
        return (10 - (sum % 10)) % 10 == s.charAt(n - 1) - '0';
    }

    private void hint(String msg) { runOnUiThread(() -> status.setText(msg)); }

    private void deliver(String text, String format) {
        try { ((Vibrator) getSystemService(VIBRATOR_SERVICE)).vibrate(60); } catch (Exception ignored) {}
        try { new ToneGenerator(AudioManager.STREAM_NOTIFICATION, 45).startTone(ToneGenerator.TONE_PROP_BEEP, 90); } catch (Exception ignored) {}
        runOnUiThread(() -> {
            Intent data = new Intent();
            data.putExtra(EXTRA_CODE, text);
            data.putExtra(EXTRA_FORMAT, format);
            setResult(RESULT_OK, data);
            finish();
        });
    }

    /* ---------------- TextureView ---------------- */
    @Override public void onSurfaceTextureAvailable(SurfaceTexture s, int w, int h) { openCamera(); }
    @Override public void onSurfaceTextureSizeChanged(SurfaceTexture s, int w, int h) {}
    @Override public boolean onSurfaceTextureDestroyed(SurfaceTexture s) { return true; }
    @Override public void onSurfaceTextureUpdated(SurfaceTexture s) {}
}
