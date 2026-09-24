# RELEASE AUDIT — 4.3.0 «گفتگوی صوتی»

**Date:** 2026-09-24 · **Verdict: PASS for release.** Full suite **739 passed / 1 skipped** (+10 new v4.3 voice tests).

---

## 1. The owner's request, translated into architecture

«مدل رو از همین مدلی که فعلاً هست نمی‌خوام سنگین‌تر بشه — صوتی باشه که هم پیام صوتی رو درک کنم هم صوتی صحبت کنم؛ گفتگوش روان و طبیعی باشه و همون متن رو صوتی بخونه.»

| Clause | Implementation |
|---|---|
| the model must NOT get heavier | **locked by test**: the registry must stay exactly the two 4.x models (same ids/bytes/sha256) and the APK's jniLibs must stay exactly one `libllamaserver.so` per ABI. Zero new model bytes. |
| understand my voice | system **SpeechRecognizer**, `fa-IR`, `EXTRA_PREFER_OFFLINE` — the same recognizer Telegram dictation uses. «گفتار» button → speak → text lands in the input (sent immediately in voice mode). `RECORD_AUDIO` asked at runtime, once. |
| speak back vocally | system **TextToSpeech** reads **the same answer text** aloud — not a different generated voice (his words: «همون متن به صورت صوتی می‌خونه»). |
| natural, fluent conversation | voice mode (ON by default): speak → question sent → answer appears AND is read aloud; a new question cuts the previous reading; per-answer «بخوان» replay; backgrounding stops the voice. |
| Windows too | web panel: mic (Web Speech API, feature-detected with an honest Persian message where the packaged WebView cannot listen), persisted «صوتی» toggle, per-answer «بخوان», auto-read, Persian OS-voice selection, listening pulse animation. |

**Why system STT/TTS and not a bundled engine:** any local alternative (whisper/Piper) means another 40–100+ MB download and another runtime — exactly what the owner excluded. The system engines are already on the device, cost zero bytes, and are what every messaging app uses. Where a device lacks a Persian TTS voice, the app says so and names the exact setting («زبان و ورودی ← خروجی تبدیل متن به گفتار») — never a silent failure.

## 2. Changed files (4.3.0)

- `mobile-android/.../BrainVoice.java` — NEW: system STT (toggle, fa-IR, offline-pref, permission flow, Persian error mapping) + system TTS (init, fa voice probe, speak/stop, utterance-completion callback) + voice-mode pref + `onBackground()`.
- `mobile-android/.../BrainScreens.java` — Chat: «گفتار» mic button, «حالت صوتی» toggle row, auto-read after paired and standalone answers, per-bubble «بخوان», stop-speak on new question.
- `mobile-android/.../AppActivity.java` — `onStop()` → `BrainVoice.onBackground()`.
- `mobile-android/app/src/main/AndroidManifest.xml` — `RECORD_AUDIO` (commented: nothing is recorded/stored).
- `frontend/brain.js` — `speakFa()` (fa-IR + Persian OS-voice pick), mic with feature detection + honest fallback message, persisted voice-mode toggle, per-answer «بخوان», auto-read, cancel-on-new-question, mic/volume icons.
- `frontend/styles.css` — voice-control styles + listening pulse animation.
- `backend/tests/test_v43_voice.py` — NEW (10 tests, see below).
- Versions: backend 4.3.0 · setup.iss 4.3.0 · Android versionCode **40300**.
- `releases/android/SupermarketMobile-4.3.0.apk` (+ `.sha256`, `.idsig`).

## 3. Test matrix (test_v43_voice.py)

1. the registry is EXACTLY the two 4.x models (ids, pinned bytes, sha prefixes) — the "no heavier model" rule.
2. the APK jniLibs contain exactly one engine per ABI — no voice binaries smuggled in.
3–4. BrainVoice uses system STT + TTS, fa-IR everywhere, offline preference, RECORD_AUDIO flow, honest Persian degradation notes, background stop.
5. manifest permission present.
6. chat wiring: mic/tapMic, voice-mode toggle, auto-read of BOTH answer paths (PC + on-phone), «بخوان», stop-on-new-question, «گفتار» label.
7. AppActivity stops voice in background.
8. web voice controls: speechSynthesis, feature-detected SpeechRecognition, fa-IR, persisted toggle, auto-read, honest unavailability message.
9. voice CSS + listening animation.
10. version pins (4.3.0 / 40300 / setup.iss).

## 4. Honest remaining

- **Voice quality depends on the device's engines** (this is the price of "no new downloads"): Google Speech Services provides Persian on most Android phones; a device without a Persian TTS voice gets the honest note + the exact setting to enable it. No physical device exists in this sandbox — the wiring is compile-verified (ecj → dex) and the flows are test-pinned, but the owner should say one sentence to his own phone before the trip.
- In the packaged Windows WebView the browser mic may be unavailable (Chromium restriction); the button then explains itself in Persian. In Chrome/Edge on the same PC it works.
