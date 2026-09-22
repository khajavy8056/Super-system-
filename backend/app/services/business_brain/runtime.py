"""v4.0 — model runtime (§28, §30, §32, §41).

One interface, three implementations:

* :class:`LlamaCppProvider` — the local model. It speaks to a **llama.cpp server**
  the Model Manager starts, over ``http://127.0.0.1:PORT/v1/chat/completions``.
  llama.cpp is chosen because it runs a ≤2 GB GGUF on a 4 GB machine with no
  Python dependency, no CUDA toolkit and no cloud account — the same binary works
  on the shop PC and (compiled) on Android. No ``llama-cpp-python`` wheel is
  added to requirements: the project deliberately avoids compiled Python wheels.
* :class:`CloudProvider` — optional, off by default, reusing the existing
  ``ai.base_url`` / ``ai.api_key`` / ``ai.model`` settings from v3.5 so there is
  exactly one place the owner configures a cloud key.
* :class:`TemplateProvider` — always available. It asks the *planner* for the
  deterministic Persian answer, which is why the brain is fully useful with no
  model installed at all (offline / 4 GB / model still downloading).

The no-invention rule is enforced here as well as in the prompt: every model call
returns text that then goes through ``grounding.verify_numbers`` before the owner
sees it, and :func:`strip_reasoning` removes `` thinking`` blocks so the model's
inner monologue is never rendered in the UI.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .. import ai_narrator
from .schemas import ToolDenied

log = logging.getLogger("supermarket.brain.runtime")

#: the model gets eight rounds — enough for a multi-domain question, bounded so a
#: looping model can never become an infinite request (§34)
MAX_TOOL_ROUNDS = 8

REASONING_BLOCK = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.S | re.I)
_ORPHAN_TAGS = re.compile(r"</?think(?:ing)?>", re.I)


def strip_reasoning(text: str) -> str:
    """Remove the model's reasoning section from anything the owner will read."""
    if not text:
        return ""
    out = REASONING_BLOCK.sub("", text)
    out = _ORPHAN_TAGS.sub("", out)
    return out.strip()


# --------------------------------------------------------------------------- contracts
@dataclass
class ProviderStatus:
    provider: str
    available: bool
    model_id: str | None = None
    binary: str | None = None
    context: int = 4096
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"provider": self.provider, "available": self.available, "model_id": self.model_id,
                "binary": self.binary, "context": self.context, "notes": list(self.notes)}


class AIProvider:
    """The abstraction the rest of the brain talks to — nothing else is imported."""

    name = "base"

    # lifecycle
    def load(self) -> bool:                                   # noqa: D401 - returns success
        return False

    def unload(self) -> bool:
        return False

    # inference
    def chat(self, messages: list[dict], *, max_tokens: int = 512, temperature: float = 0.7) -> str:
        raise NotImplementedError

    def generate(self, prompt: str, *, max_tokens: int = 512, system: str | None = None) -> str:
        messages = ([{"role": "system", "content": system}] if system else []) + \
                   [{"role": "user", "content": prompt}]
        return self.chat(messages, max_tokens=max_tokens)

    def structured_output(self, prompt: str, schema: dict, *, retries: int = 1) -> dict | None:
        """Ask for JSON and parse it. Returns ``None`` rather than guessing."""
        instruction = ("فقط و فقط یک شیء JSON برگردان که با این ساختار بخواند: "
                       f"{json.dumps(schema, ensure_ascii=False)}")
        for _ in range(retries + 1):
            raw = self.chat([{"role": "user", "content": f"{prompt}\n\n{instruction}"}],
                            temperature=0.2, max_tokens=400)
            parsed = extract_json(raw)
            if isinstance(parsed, dict):
                return parsed
        return None

    def tool_call(self, prompt: str, tools: list[dict]) -> dict | None:
        """One tool call as ``{"name": ..., "arguments": {...}}`` or ``None``."""
        schema = {"name": "tool name from the provided list",
                  "arguments": {"any parameter": "value"}}
        payload = self.structured_output(prompt, schema)
        if not payload:
            return None
        name = payload.get("name") or payload.get("tool")
        known = {t.get("name") for t in tools}
        if not name or (known and name not in known):
            return None
        args = payload.get("arguments") or payload.get("params") or {}
        return {"name": name, "arguments": args if isinstance(args, dict) else {}}

    def health_check(self) -> dict:
        return {"ok": self.available(), "provider": self.name}

    def benchmark(self, *, prompts: Iterable[str] = ()) -> dict:
        return {"provider": self.name, "available": self.available()}


#: §33 — sampling presets. ``thinking`` is for models that expose a reasoning
#: channel (Qwen3's ``/think``); ``fast`` is the default for everyday answers.
#: A model without the ``thinking`` capability always gets ``fast``.
SAMPLING: dict[str, dict] = {
    "thinking": {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0},
    "fast": {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0},
}

#: llama.cpp's OpenAI-compatible server. 8765 is *not* used anywhere in v4.0 —
#: the store PC may already run something on it, and one port in one place is
#: easier to audit than two.
DEFAULT_PORT = 8080


def preset_for(model_id: str | None, asked: str | None = None) -> dict:
    """Pick the sampling preset for a model, honouring an explicit request."""
    if asked in SAMPLING:
        return dict(SAMPLING[asked])
    from .model_registry import get as get_spec

    spec = get_spec(model_id) if model_id else None
    if spec is not None and "thinking" in (spec.capabilities or ()):
        return dict(SAMPLING["thinking"])
    return dict(SAMPLING["fast"])


def server_port(db=None) -> int:
    """The single place that decides which port llama-server listens on."""
    if db is None:
        return DEFAULT_PORT
    try:
        from .policies import get_value
        return int(get_value(db, "brain.runtime.port", DEFAULT_PORT) or DEFAULT_PORT)
    except Exception:  # noqa: BLE001 — a bad setting must not break the chat
        return DEFAULT_PORT


# --------------------------------------------------------------------------- local llama.cpp
class LlamaCppProvider(AIProvider):
    """llama.cpp server on localhost. Started by the Model Manager, never by a request."""

    name = "llama_cpp"

    def __init__(self, *, model_id: str, model_path: str | None = None, binary: str | None = None,
                 host: str = "127.0.0.1", port: int = DEFAULT_PORT, context: int = 4096,
                 threads: int | None = None, extra_args: list[str] | None = None,
                 start_server: bool = True) -> None:
        self.model_id = model_id
        self.model_path = model_path or ""
        self.binary = binary
        self.host, self.port = host, int(port)
        self.context = int(context)
        self.threads = threads or max(1, (os.cpu_count() or 2) - 1)
        self.extra_args = list(extra_args or [])
        self.start_server = start_server
        self._process: subprocess.Popen | None = None
        self._notes: list[str] = []

    # ------------------------------------------------------------------ lifecycle
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _healthy(self, timeout: float = 2.0) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url()}/health", timeout=timeout) as r:
                return r.status == 200
        except Exception:  # noqa: BLE001 — "not up yet" is a normal answer
            return False

    def available(self) -> bool:
        if not self.model_path or not os.path.exists(self.model_path):
            return False
        if not self.binary or not os.path.exists(self.binary):
            return False
        return True

    def load(self) -> bool:
        if not self.available():
            self._notes = ["فایل مدل یا فایل اجرایی llama.cpp در دسترس نیست"]
            return False
        if self._healthy():
            return True
        if not self.start_server:
            self._notes = ["سرور llama.cpp در حال اجرا نیست"]
            return False
        cmd = [self.binary, "-m", self.model_path, "--host", self.host, "--port", str(self.port),
               "-c", str(self.context), "-t", str(self.threads), "--no-webui", *self.extra_args]
        try:
            self._process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
        except OSError as exc:
            self._notes = [f"اجرای llama.cpp ناموفق: {exc}"]
            return False
        deadline = time.time() + 120
        while time.time() < deadline:
            if self._healthy():
                return True
            if self._process.poll() is not None:
                self._notes = ["فرایند llama.cpp بلافاصله بسته شد (احتمال کمبود حافظه)"]
                return False
            time.sleep(1.0)
        self._notes = ["مدل در بازهٔ مجاز بارگذاری نشد"]
        self.unload()
        return False

    def unload(self) -> bool:
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None
        return True

    # ------------------------------------------------------------------ inference
    def chat(self, messages: list[dict], *, max_tokens: int = 512, temperature: float | None = None,
             preset: str | None = None) -> str:
        if not self._healthy():
            if not self.load():
                raise RuntimeError("MODEL_NOT_AVAILABLE")
        params = preset_for(self.model_id, preset)
        if temperature is not None:
            params["temperature"] = temperature
        body = json.dumps({"messages": messages, "max_tokens": max_tokens, "stream": False,
                           **params, "chat_template_kwargs": {"enable_thinking": False}}).encode()
        req = urllib.request.Request(f"{self.base_url()}/v1/chat/completions", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            payload = json.loads(r.read().decode())
        content = payload["choices"][0]["message"]["content"]
        return strip_reasoning(content)

    # ------------------------------------------------------------------ honesty
    def health_check(self) -> dict:
        return {"ok": self._healthy(), "provider": self.name, "model_id": self.model_id}

    def benchmark(self, *, prompts: Iterable[str] = ()) -> dict:
        """Real measurements only — never a fabricated score."""
        out: dict = {"provider": self.name, "model_id": self.model_id}
        if not self.available():
            return {**out, "available": False}
        out["available"] = True
        t0 = time.time()
        out["load_ok"] = self.load()
        out["load_ms"] = int((time.time() - t0) * 1000)
        if not out["load_ok"]:
            out["notes"] = list(self._notes)
            return out
        results = []
        for prompt in list(prompts) or ["در یک جمله بگو امروز فروشگاه چه وضعیتی دارد."]:
            t1 = time.time()
            try:
                text = self.chat([{"role": "user", "content": prompt}], max_tokens=64)
            except Exception as exc:  # noqa: BLE001
                results.append({"ok": False, "error": str(exc)[:120]})
                continue
            elapsed = max(0.001, time.time() - t1)
            results.append({"ok": True, "ms": int(elapsed * 1000),
                            "chars_per_sec": round(len(text) / elapsed, 1),
                            "persian": bool(re.search(r"[\u0600-\u06FF]", text))})
        ok = [r for r in results if r.get("ok")]
        out["runs"] = results
        out["avg_ms"] = int(sum(r["ms"] for r in ok) / len(ok)) if ok else None
        out["chars_per_sec"] = round(sum(r.get("chars_per_sec", 0) for r in ok) / len(ok), 1) if ok else 0
        out["persian_ok"] = all(r.get("persian") for r in ok) if ok else False
        out["tool_call_ok"] = self._tool_call_bench()
        out["memory_mb"] = _rss_mb()
        return out

    def _tool_call_bench(self) -> bool:
        try:
            call = self.tool_call('از این ابزارها استفاده کن: [{"name": "get_cash_position"}] — '
                                  'سؤال: موجودی نقد چقدر است؟', [{"name": "get_cash_position"}])
            return bool(call and call.get("name") == "get_cash_position")
        except Exception:  # noqa: BLE001
            return False


def _rss_mb() -> int | None:
    try:
        with open("/proc/self/statm") as fh:
            pages = int(fh.read().split()[1])
        return int(pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024))
    except Exception:  # noqa: BLE001 — Windows has no /proc
        return None


# --------------------------------------------------------------------------- cloud (opt-in)
class CloudProvider(AIProvider):
    """Reuses the v3.5 narrator settings. Never the default, never required."""

    name = "cloud"

    def __init__(self, db, *, model_id: str | None = None) -> None:
        self.db = db
        self.model_id = model_id or ai_narrator.configured(db).get("model")

    def available(self) -> bool:
        conf = ai_narrator.configured(self.db)
        return bool(conf.get("online"))

    def chat(self, messages: list[dict], *, max_tokens: int = 512, temperature: float = 0.7) -> str:
        return strip_reasoning(ai_narrator._chat(self.db, messages, max_tokens=max_tokens))


# --------------------------------------------------------------------------- deterministic
class TemplateProvider(AIProvider):
    """No model: the planner's own Persian text, verbatim."""

    name = "deterministic"

    def __init__(self, renderer: Callable[[], str] | None = None) -> None:
        self._renderer = renderer

    def available(self) -> bool:
        return True

    def chat(self, messages: list[dict], *, max_tokens: int = 512, temperature: float = 0.7) -> str:
        return self._renderer() if self._renderer else ""

    def structured_output(self, prompt: str, schema: dict, *, retries: int = 1) -> dict | None:
        return None

    def tool_call(self, prompt: str, tools: list[dict]) -> dict | None:
        return None


# --------------------------------------------------------------------------- selection
DEFAULT_MODES = ("local_only", "local_preferred", "cloud_fallback", "cloud_only")


def get_runtime(db=None, *, renderer: Callable[[], str] | None = None) -> AIProvider:
    """Pick the provider that matches the owner's declared mode (§52).

    ``local_only`` (the default) can only ever return a local or deterministic
    provider — the privacy default is enforced here, not in the UI.
    """
    from .model_manager import active_install, find_binary
    from .policies import get_value

    mode = str(get_value(db, "ai_mode", "local_only") or "local_only") if db is not None else "local_only"
    if mode not in DEFAULT_MODES:
        mode = "local_only"
    install = active_install(db) if db is not None else None
    if install is not None:
        from .model_registry import get as get_spec

        spec = get_spec(install.model_id)
        provider = LlamaCppProvider(
            model_id=install.model_id, model_path=install.path, binary=find_binary(),
            context=int((spec.context_default if spec else 4096)),
        )
        if provider.available():
            return provider
        # an install that cannot run must be visible, never silently swapped
        log.warning("active model %s is not runnable; using deterministic answers", install.model_id)
    if mode in ("cloud_fallback", "cloud_only") and db is not None:
        allow = bool(get_value(db, "allow_cloud_ai", False))
        cloud = CloudProvider(db)
        if allow and cloud.available():
            return cloud
    return TemplateProvider(renderer)


def provider_status(db=None) -> dict:
    """Honest status for the UI: which engine is answering right now, and why."""
    from .model_manager import active_install, find_binary

    mode = "local_only"
    install = None
    if db is not None:
        from .policies import get_value
        mode = str(get_value(db, "ai_mode", "local_only") or "local_only")
        install = active_install(db)
    local_ok = bool(install and find_binary())
    notes = []
    if install is None:
        notes.append("مدلی نصب نشده؛ پاسخ‌ها از موتور قطعی می‌آید")
    if install is not None and not find_binary():
        notes.append("فایل اجرایی llama.cpp پیدا نشد")
    if mode in ("cloud_fallback", "cloud_only"):
        notes.append("حالت ابری انتخاب شده است")
    provider = "llama_cpp" if local_ok else ("cloud" if mode in ("cloud_only",) else "deterministic")
    return {"mode": mode, "provider": provider, "local_available": local_ok,
            "model_id": install.model_id if install else None, "notes": notes}


# --------------------------------------------------------------------------- tool loop
class ToolLoop:
    """The only place the model is allowed to *ask* for data (§34).

    The loop is deliberately strict, because a 1.5B model on a shop PC is not a
    reliable structured-output engine:

    * the model receives the read-only tool catalogue and the situation digest —
      never the database, never the whole conversation;
    * every call goes through :class:`~.registry.ToolRegistry`, so the permission
      check, the parameter check and the audit trail happen exactly as they do
      for the deterministic path;
    * the loop is capped (``max_rounds``, default 8) and the last round is spent
      asking for an answer with no tools at all;
    * reasoning text and JSON are stripped from what the owner finally reads.
    """

    ANSWER_KEYS = ("answer", "reply", "final", "text")
    TOOL_KEYS = ("tool", "tool_name", "name", "action")

    def __init__(self, *, runtime: AIProvider, ctx, max_rounds: int = MAX_TOOL_ROUNDS) -> None:
        self.runtime = runtime
        self.ctx = ctx
        self.max_rounds = max(1, int(max_rounds))
        self.rounds = 0
        self.calls: list[dict] = []

    # ------------------------------------------------------------------ helpers
    def _catalogue(self) -> list[dict]:
        from .registry import REGISTRY

        return REGISTRY.for_llm(self.ctx)

    def _parse(self, text: str) -> dict | None:
        """Read either a tool request or a final answer out of the model's reply."""
        payload = extract_json(text)
        if not isinstance(payload, dict):
            return None
        for key in self.ANSWER_KEYS:
            if isinstance(payload.get(key), str) and payload[key].strip():
                return {"kind": "answer", "answer": payload[key]}
        for key in self.TOOL_KEYS:
            name = payload.get(key)
            if isinstance(name, str) and name.strip():
                args = payload.get("arguments") or payload.get("params") or payload.get("args") or {}
                return {"kind": "tool", "name": name.strip(),
                        "arguments": args if isinstance(args, dict) else {}}
        return None

    def _run_tool(self, name: str, args: dict) -> str:
        from .registry import REGISTRY

        try:
            call = REGISTRY.call(self.ctx, name, args)
        except ToolDenied as exc:
            self.calls.append({"name": name, "ok": False, "error": f"TOOL_DENIED: {exc}"})
            return json.dumps({"ok": False, "error": "TOOL_DENIED"}, ensure_ascii=False)
        self.calls.append({"name": name, "ok": bool(call.ok), "error": call.error})
        if not call.ok:
            return json.dumps({"ok": False, "error": call.error or "TOOL_FAILED"},
                              ensure_ascii=False)
        payload = {"ok": True, "summary": call.summary, "numbers": call.numbers}
        return json.dumps(payload, ensure_ascii=False, default=str)[:4000]

    # --------------------------------------------------------------------- run
    def run(self, *, system: str, user: str) -> str | None:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        tools = self._catalogue()
        last_text = ""
        for round_index in range(self.max_rounds):
            self.rounds = round_index + 1
            try:
                text = self.runtime.chat(messages, max_tokens=500)
            except Exception as exc:  # noqa: BLE001 — a dead model must not break the answer
                log.warning("model chat failed on round %s: %s", self.rounds, exc)
                return None
            text = strip_reasoning(text or "")
            last_text = text
            parsed = self._parse(text)
            if parsed is None:
                return clean_answer(text)
            if parsed["kind"] == "answer":
                return clean_answer(parsed["answer"])
            result = self._run_tool(parsed["name"], parsed["arguments"])
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user",
                             "content": f"[نتیجهٔ ابزار {parsed['name']}]\n{result}\n\n"
                                        "پاسخ نهایی را کوتاه و فارسی بده؛ عدد جدیدی از خودت نساز."})
        # out of rounds: one final attempt, with the tool catalogue withdrawn
        try:
            final = self.runtime.chat(messages + [{"role": "user",
                                                   "content": "حالا فقط پاسخ نهایی فارسی را بده."}],
                                      max_tokens=400)
        except Exception:  # noqa: BLE001
            return clean_answer(last_text) or None
        return clean_answer(final)


def clean_answer(text: str) -> str | None:
    """Never show the owner a tool call, a JSON blob or a reasoning block."""
    if not text:
        return None
    out = strip_reasoning(text)
    out = re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", out, flags=re.S)
    if out.lstrip().startswith("{"):
        payload = extract_json(out)
        if isinstance(payload, dict):
            for key in ToolLoop.ANSWER_KEYS:
                if isinstance(payload.get(key), str):
                    out = payload[key]
                    break
            else:
                return None
    out = out.strip()
    return out or None

# --------------------------------------------------------------------------- parsing helpers
def extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of a model answer (code fences tolerated)."""
    if not text:
        return None
    cleaned = strip_reasoning(text)
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.S)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        candidate = cleaned[start:end + 1] if start >= 0 and end > start else None
    if not candidate:
        return None
    try:
        parsed = json.loads(candidate)
    except ValueError:
        try:
            parsed = json.loads(re.sub(r",\s*([}\]])", r"\1", candidate))
        except ValueError:
            return None
    return parsed if isinstance(parsed, dict) else None
