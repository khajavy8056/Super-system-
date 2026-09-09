package ir.khajavy.supermarket;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

/** v2.1 — kept for the smkt:// deep link; the pairing UI now lives in {@link SetupActivity}. */
public class PairActivity extends Activity {
    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        Intent i = new Intent(this, SetupActivity.class);
        if (getIntent() != null && getIntent().getData() != null) i.setData(getIntent().getData());
        startActivity(i); finish();
    }
}
