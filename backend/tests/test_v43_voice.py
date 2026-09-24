"""v4.3 — voice conversation, locked down as tests.

Owner's request (round 8): «مدل رو از همین مدلی که فعلاً هست نمی‌خوام سنگین‌تر
بشه — صوتی باشه که هم پیام صوتی رو درک کنم هم صوتی صحبت کنم؛ همون متن رو
صوتی بخونه». Two hard rules:

  1. the AI MODEL STAYS EXACTLY THE SAME (no heavier/second model, no new
     multi-hundred-MB download);
  2. voice = ears (system speech recognizer, fa-IR) + mouth (system TTS reading
     THE SAME answer text aloud) — nothing is recorded or sent anywhere.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

ANDROID = ROOT / "mobile-android" / "app" / "src" / "main" / "java" / "ir" / "khajavy" / "supermarket"


# ---------------------------------------------------------------- rule 1: the model is untouched
def test_the_model_did_not_get_heavier():
    """The registry must still be EXACTLY the two 4.x models — same ids, same
    pinned bytes, same sha256. Voice must not cost a single model byte."""
    from app.services.business_brain import model_registry as reg
    specs = {m.model_id: m for m in reg.all_models()}
    assert set(specs) == {
        "qwen2.5-1.5b-instruct-q4_k_m",
        "qwen2.5-1.5b-instruct-q3_k_m",
    }
    assert specs["qwen2.5-1.5b-instruct-q4_k_m"].file_size_bytes == 1_117_320_736
    assert specs["qwen2.5-1.5b-instruct-q3_k_m"].file_size_bytes == 924_455_968
    assert specs["qwen2.5-1.5b-instruct-q4_k_m"].sha256.startswith("6a1a2eb6")
    assert specs["qwen2.5-1.5b-instruct-q3_k_m"].sha256.startswith("58cb5c05")


def test_no_new_model_files_shipped():
    """No extra engine/model binaries joined the Android package for voice."""
    jni = ROOT / "mobile-android" / "app" / "src" / "main" / "jniLibs"
    abis = {d.name: sorted(f.name for f in d.iterdir()) for d in jni.iterdir() if d.is_dir()}
    assert set(abis) == {"arm64-v8a", "armeabi-v7a"}
    assert all(v == ["libllamaserver.so"] for v in abis.values())


# ---------------------------------------------------------------- Android voice
def test_brain_voice_exists_with_system_stt_and_tts():
    t = (ANDROID / "BrainVoice.java").read_text(encoding="utf-8")
    assert "TextToSpeech" in t                       # mouth: system TTS
    assert "SpeechRecognizer" in t                   # ears: system recognizer
    assert '"fa", "IR"' in t and '"fa-IR"' in t      # Persian everywhere
    assert "EXTRA_PREFER_OFFLINE" in t               # offline when possible
    assert "RECORD_AUDIO" in t and "REQ_MIC" in t    # runtime permission flow
    assert "صدای فارسی روی این دستگاه نصب نیست" in t   # honest degradation note
    assert "onBackground" in t                       # never talk behind the user's back


def test_manifest_has_record_audio():
    m = (ROOT / "mobile-android" / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert 'android.permission.RECORD_AUDIO' in m


def test_chat_is_voice_wired():
    s = (ANDROID / "BrainScreens.java").read_text(encoding="utf-8")
    assert "tapMic" in s and "BrainVoice.toggleListen" in s      # mic → recognizer → input
    assert "حالت صوتی" in s and "BrainVoice.voiceMode()" in s     # the voice-mode toggle
    assert "BrainVoice.speak(c, x.optString(\"text\"), null)" in s  # auto-read PC answers
    assert "BrainVoice.speak(c, answer, null)" in s                # auto-read standalone answers
    assert "بخوان" in s                                            # per-bubble replay button
    assert "BrainVoice.stopSpeak()" in s                           # new question cuts the speech
    assert '"گفتار"' in s                                          # the mic button label


def test_activity_stops_voice_in_background():
    a = (ANDROID / "AppActivity.java").read_text(encoding="utf-8")
    assert "BrainVoice.onBackground()" in a


# ---------------------------------------------------------------- Windows / web voice
def test_web_chat_voice_controls():
    js = (ROOT / "frontend" / "brain.js").read_text(encoding="utf-8")
    assert "speechSynthesis" in js                     # read-aloud
    assert "SpeechRecognition || window.webkitSpeechRecognition" in js   # feature-detected mic
    assert '"fa-IR"' in js                             # both directions Persian
    assert "brainVoiceMode" in js                      # persisted toggle
    assert "speakFa(answer.text)" in js                # auto-read the SAME text
    assert "brain-mic" in js and "brain-vm" in js      # the buttons exist
    assert "بخوان" in js                               # per-answer replay
    assert "کروم/اج یا در اپ اندروید" in js             # honest unavailability message


def test_voice_css_exists():
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    assert ".brain-mic" in css and ".brain-vm" in css and ".brain-read" in css
    assert "brainMic" in css                           # listening pulse animation


# ---------------------------------------------------------------- versions
def test_versions_consistent():
    from app import __version__
    assert (ROOT / "backend" / "app" / "__init__.py").read_text(
        encoding="utf-8").count(f'__version__ = "{__version__}"') == 1
    iss = (ROOT / "installer" / "windows" / "setup.iss").read_text(encoding="utf-8-sig")
    assert f'#define MyAppVersion "{__version__}"' in iss
