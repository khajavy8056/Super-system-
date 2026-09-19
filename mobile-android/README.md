# سوپرمارکت — اپلیکیشن اندروید (§257)

پوستهٔ بومی اندروید برای PWA موبایل سیستم (`/mobile/`). همان صفحهٔ انبارگردانی/اسکن بارکد
که در مرورگر اجرا می‌شود، اینجا داخل یک WebView با دسترسی دوربین و صف آفلاین اجرا می‌گردد.

## چرا WebView و نه TWA؟
TWA به دامنهٔ عمومی HTTPS و Digital Asset Links نیاز دارد. این سیستم local-first است و سرور
روی رایانهٔ فروشگاه در شبکهٔ داخلی با HTTP ساده اجرا می‌شود (§259)؛ بنابراین WebView تنها راه
صادقانه است. ترافیک cleartext فقط برای رنج‌های خصوصی (`192.168.*`, `10.*`, `172.16.*`, `localhost`)
مجاز است (`res/xml/network_security_config.xml`).

## ساخت
- Android Studio Koala یا جدیدتر → Open → پوشهٔ `mobile-android` → Build → Build APK.
- خط فرمان (با Android SDK نصب‌شده): `gradle assembleRelease` یا `./gradlew assembleRelease`
  (wrapper را با `gradle wrapper --gradle-version 8.7` بسازید).
- CI: `installer/ci/release-android.yml` روی `ubuntu-latest` می‌سازد و `SupermarketMobile-<ver>.apk`
  را به Release ضمیمه می‌کند. شمارهٔ نسخه از `backend/app/__init__.py` خوانده می‌شود.

## امضا
بدون keystore، APK با کلید debug امضا می‌شود (برای نصب مستقیم روی گوشی‌های فروشگاه کافی است).
برای انتشار عمومی متغیرهای `SUPERMARKET_KEYSTORE`, `SUPERMARKET_KEYSTORE_PASSWORD`,
`SUPERMARKET_KEY_ALIAS`, `SUPERMARKET_KEY_PASSWORD` را تنظیم کنید.

## وضعیت صداقت (§57)
کد کامل است اما در محیط توسعهٔ فعلی Android SDK/JDK در دسترس نبود؛ بنابراین ساخت APK
**NOT VERIFIED** است تا زمانی که workflow اندروید یک بار روی GitHub Actions اجرا شود.
