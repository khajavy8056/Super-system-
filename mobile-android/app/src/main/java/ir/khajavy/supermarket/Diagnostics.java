package ir.khajavy.supermarket;

/** Bounded, local-only crash diagnostics. No exception messages, tokens or customer data. */
public final class Diagnostics extends android.app.Application {
    @Override public void onCreate() {
        super.onCreate();
        final Thread.UncaughtExceptionHandler previous = Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler((thread, error) -> {
            try {
                StringBuilder report = new StringBuilder("Version: ").append(Version.NAME)
                    .append("\nAndroid API: ").append(android.os.Build.VERSION.SDK_INT)
                    .append("\nModel: ").append(android.os.Build.MANUFACTURER).append(" ").append(android.os.Build.MODEL)
                    .append("\nABI: ").append(java.util.Arrays.toString(android.os.Build.SUPPORTED_ABIS))
                    .append("\nTime: ").append(System.currentTimeMillis());
                Throwable cause = error;
                for (int depth = 0; cause != null && depth < 4; depth++, cause = cause.getCause()) {
                    report.append("\nType: ").append(cause.getClass().getName());
                    StackTraceElement[] stack = cause.getStackTrace();
                    for (int i = 0; i < Math.min(32, stack.length); i++) report.append("\n at ").append(stack[i]);
                }
                try (java.io.FileOutputStream file = openFileOutput("last-crash.txt", MODE_PRIVATE)) {
                    file.write(report.toString().getBytes("UTF-8"));
                }
            } catch (Throwable ignored) { /* diagnostics must never replace the original failure */ }
            if (previous != null) previous.uncaughtException(thread, error);
            else { android.os.Process.killProcess(android.os.Process.myPid()); System.exit(10); }
        });
    }
    public static String last(android.content.Context context) {
        try (java.io.FileInputStream file = context.openFileInput("last-crash.txt")) {
            byte[] bytes = new byte[16384]; int n = file.read(bytes);
            return n <= 0 ? "" : new String(bytes, 0, n, "UTF-8");
        } catch (Exception ignored) { return ""; }
    }
    @Override public void onTrimMemory(int level) {
        super.onTrimMemory(level);
        if (level >= TRIM_MEMORY_RUNNING_LOW) Images.MEM.evictAll();
    }
}
