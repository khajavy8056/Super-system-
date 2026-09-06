package ir.khajavy.supermarket;

import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;

import androidx.appcompat.app.AppCompatActivity;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** First-run screen: ask for the shop server address and verify it really is our backend. */
public class SetupActivity extends AppCompatActivity {
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_setup);
        EditText url = findViewById(R.id.server_url);
        TextView status = findViewById(R.id.status);
        Button test = findViewById(R.id.btn_test);
        Button save = findViewById(R.id.btn_save);

        String existing = Prefs.serverUrl(this);
        if (existing != null) url.setText(existing);

        test.setOnClickListener(v -> probe(Prefs.normalise(url.getText().toString()), status, null));
        save.setOnClickListener(v -> {
            String s = Prefs.normalise(url.getText().toString());
            probe(s, status, () -> {
                Prefs.setServerUrl(this, s);
                startActivity(new Intent(this, MainActivity.class));
                finish();
            });
        });
    }

    /** GET {server}/health and accept only a JSON body from this system. */
    private void probe(String base, TextView status, Runnable onOk) {
        if (base.isEmpty()) { status.setText(R.string.setup_fail); return; }
        status.setText("…");
        io.execute(() -> {
            boolean ok = false;
            try {
                HttpURLConnection c = (HttpURLConnection) new URL(base + "/health").openConnection();
                c.setConnectTimeout(4000);
                c.setReadTimeout(4000);
                if (c.getResponseCode() == 200) {
                    BufferedReader r = new BufferedReader(new InputStreamReader(c.getInputStream(), "UTF-8"));
                    StringBuilder sb = new StringBuilder();
                    String line;
                    while ((line = r.readLine()) != null) sb.append(line);
                    ok = sb.toString().contains("Supermarket System");
                }
                c.disconnect();
            } catch (Exception ignored) {
            }
            final boolean result = ok;
            ui.post(() -> {
                status.setText(result ? R.string.setup_ok : R.string.setup_fail);
                if (result && onOk != null) onOk.run();
            });
        });
    }
}
