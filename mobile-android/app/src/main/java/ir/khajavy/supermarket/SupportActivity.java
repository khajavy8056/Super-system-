package ir.khajavy.supermarket;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.view.Gravity;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

/**
 * v2.1 — support contact that works EVERYWHERE: before setup, when locked, in
 * standalone mode. Uses the very same support system as Windows: a ticket is
 * composed and relayed through the vendor's support inbox (bot relay). With a
 * paired PC the ticket goes through the PC (so it is tracked there); without a
 * PC the phone relays it directly, with the phone's own installation code.
 */
public class SupportActivity extends Activity {
    @Override protected void onCreate(Bundle b) {
        super.onCreate(b); Prefs.init(this); Db.init(this); Ui.init(this); LockActivity.top = this;
        getWindow().setStatusBarColor(Ui.BG);
        LinearLayout root = Ui.col(this); root.setBackgroundColor(Ui.BG); root.setPadding(Ui.dp(20), Ui.dp(36), Ui.dp(20), Ui.dp(24));
        TextView t = Ui.h1(this, "ارتباط با پشتیبانی"); root.addView(t);
        root.addView(Ui.muted(this, "پیام شما مستقیم به پشتیبانی «" + getString(R.string.app_name) + "» می‌رسد و پاسخ، در همین برنامه (بخش پشتیبانی) نمایش داده می‌شود."));
        LinearLayout cd = Ui.card(this, null);
        EditText subj = Ui.input(this, "موضوع *"); EditText desc = Ui.area(this, "شرح مشکل / درخواست"); EditText contact = Ui.input(this, "شمارهٔ تماس شما", true);
        contact.setText(Prefs.get("store_mobile", ""));
        cd.addView(subj); cd.addView(desc); cd.addView(contact);
        TextView st = Ui.muted(this, ""); cd.addView(st);
        cd.addView(Ui.primary(this, "ارسال به پشتیبانی", () -> {
            if (Ui.str(subj).length() < 3) { Ui.toast("موضوع کوتاه است"); return; }
            st.setText("در حال ارسال…");
            JSONObject body = Api.obj("type", Lic.allowed() ? "QUESTION" : "LICENSE", "priority", "HIGH", "subject", Ui.str(subj), "description", Ui.str(desc), "contact", Ui.str(contact), "device", "android-native/" + Version.NAME);
            Api.bg(() -> {
                String err = null;
                if (!Api.standalone()) { try { Api.call("POST", "/support/tickets", body.toString(), "application/json"); } catch (Api.ApiError e) { if (e.status == 402 || e.offline()) err = SupportRelay.send(body); else err = e.getMessage(); } }
                else err = SupportRelay.send(body);
                final String fe = err;
                Api.ui(() -> { if (fe == null) { st.setText("ارسال شد ✓ — پشتیبانی با شما تماس می‌گیرد"); subj.setText(""); desc.setText(""); } else st.setText(fe); });
            });
        }));
        root.addView(cd);
        LinearLayout info = Ui.card(this, "اطلاعات این نصب");
        info.addView(Ui.kv(this, "کد نصب", SupportRelay.installCode(), 0));
        info.addView(Ui.kv(this, "نسخهٔ برنامه", Ui.fa(Version.NAME), 0));
        info.addView(Ui.kv(this, "وضعیت لایسنس", Lic.allowed() ? "فعال" : Lic.reason(), Lic.allowed() ? Ui.GREEN : Ui.RED));
        root.addView(info);
        root.addView(Ui.ghost(this, "بازگشت", this::finish));
        setContentView(Ui.scroll(this, root));
    }
}
