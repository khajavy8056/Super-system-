"""v4.0 — the execution context every tool runs inside.

A tool never receives a raw ``Session`` plus a free hand: it receives a
``ToolContext`` carrying *who is asking* (user + permission set), *what time it
is in the store*, a per-request cache for expensive reads, and the trace list
that becomes the decision's audit trail. That is what makes
"the LLM cannot bypass RBAC" a structural property instead of a promise.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from ...models import User
from .schemas import ToolCall


@dataclass
class ToolContext:
    db: Session
    user: User | None = None
    #: permission codes the caller holds (empty + user=None means "system/worker")
    permissions: frozenset[str] = frozenset()
    #: set by the caller when it runs outside a user request (proactive worker)
    system: bool = False
    now: datetime = field(default_factory=datetime.utcnow)
    trace: list[ToolCall] = field(default_factory=list)
    cache: dict = field(default_factory=dict)
    #: hard ceiling for a single tool call, in milliseconds (surfaced in the trace)
    tool_budget_ms: int = 8000

    def has(self, code: str) -> bool:
        return True if self.system else code in self.permissions

    def cached(self, key: str, producer):
        if key not in self.cache:
            self.cache[key] = producer()
        return self.cache[key]

    def record(self, call: ToolCall) -> ToolCall:
        self.trace.append(call)
        return call

    def trace_payload(self) -> list[dict]:
        return [c.trace() for c in self.trace]

    #: numbers produced by deterministic tools during this context's lifetime.
    #: ``grounding.py`` checks every money number the model writes against this.
    def register_numbers(self, data: dict) -> None:
        bag = self.cache.setdefault("__numbers__", set())
        for value in _walk_numbers(data):
            bag.add(round(float(value), 2))

    def known_numbers(self) -> set[float]:
        return set(self.cache.get("__numbers__", set()))


def _walk_numbers(node, depth: int = 0):
    """Yield every numeric leaf of a nested structure (bounded depth)."""
    if depth > 6:
        return
    if isinstance(node, bool):
        return
    if isinstance(node, (int, float)):
        yield node
        return
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).startswith("_"):
                continue
            yield from _walk_numbers(value, depth + 1)
    elif isinstance(node, (list, tuple)):
        for item in node[:200]:
            yield from _walk_numbers(item, depth + 1)


class Timer:
    """Tiny ms timer used by the registry to report real tool latency."""

    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = int((time.perf_counter() - self.t0) * 1000)
        return False
