"""tests/bd_agent/conversation/test_history.py

Tests for InMemoryHistory (T-050).

Scenarios:
- append and get round-trip
- sliding window: exceeding max_pairs drops oldest pair
- multiple JIDs are isolated
- get on unknown JID returns empty list
- clear(jid) removes only that JID
- clear on unknown JID is a no-op
- sweep_idle removes JIDs silent > idle_timeout, returns count
- sweep_idle does not remove recently-active JIDs
- sweep_idle returns 0 when nothing to clear
"""
from __future__ import annotations

import time

import pytest

from bd_agent.contracts import Message
from bd_agent.conversation.history import InMemoryHistory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user(text: str) -> Message:
    return Message(role="user", content=text)


def _assistant(text: str) -> Message:
    return Message(role="assistant", content=text)


# ---------------------------------------------------------------------------
# Basic append / get
# ---------------------------------------------------------------------------


def test_append_and_get_single_pair():
    h = InMemoryHistory()
    h.append("jid1", _user("hola"))
    h.append("jid1", _assistant("hola, ¿en qué te ayudo?"))
    messages = h.get("jid1")
    assert len(messages) == 2
    assert messages[0].content == "hola"
    assert messages[1].content == "hola, ¿en qué te ayudo?"


def test_get_unknown_jid_returns_empty():
    h = InMemoryHistory()
    assert h.get("unknown@s.whatsapp.net") == []


def test_get_returns_messages_in_order():
    h = InMemoryHistory()
    for i in range(5):
        h.append("jid1", _user(f"msg {i}"))
    messages = h.get("jid1")
    assert [m.content for m in messages] == [f"msg {i}" for i in range(5)]


# ---------------------------------------------------------------------------
# Sliding window (max_pairs)
# ---------------------------------------------------------------------------


def test_sliding_window_drops_oldest_pair():
    """max_pairs=2 means at most 4 messages (2 user + 2 assistant)."""
    h = InMemoryHistory(max_pairs=2)
    h.append("jid1", _user("turn1-user"))
    h.append("jid1", _assistant("turn1-assistant"))
    h.append("jid1", _user("turn2-user"))
    h.append("jid1", _assistant("turn2-assistant"))
    # Now add a third pair — first pair must be dropped
    h.append("jid1", _user("turn3-user"))
    h.append("jid1", _assistant("turn3-assistant"))
    messages = h.get("jid1")
    contents = [m.content for m in messages]
    assert "turn1-user" not in contents
    assert "turn1-assistant" not in contents
    assert "turn2-user" in contents
    assert "turn3-assistant" in contents


def test_sliding_window_exact_max_pairs_kept():
    """Exactly max_pairs pairs are retained when threshold hit."""
    h = InMemoryHistory(max_pairs=3)
    for i in range(3):
        h.append("jid1", _user(f"u{i}"))
        h.append("jid1", _assistant(f"a{i}"))
    # At exactly max_pairs nothing is dropped yet
    assert len(h.get("jid1")) == 6

    # Add one more pair: oldest must drop
    h.append("jid1", _user("u3"))
    h.append("jid1", _assistant("a3"))
    messages = h.get("jid1")
    assert len(messages) == 6  # still 3 pairs
    assert messages[0].content == "u1"


def test_sliding_window_single_message_does_not_drop_pair():
    """Adding one message of a new pair does not yet drop an old pair."""
    h = InMemoryHistory(max_pairs=2)
    h.append("jid1", _user("u1"))
    h.append("jid1", _assistant("a1"))
    h.append("jid1", _user("u2"))
    h.append("jid1", _assistant("a2"))
    # Buffer full at 2 pairs — adding a single user message starts pair 3
    # but pair 1 should only drop once pair 3 is complete (or immediately on
    # overflow — implementation decides; what matters is window stays bounded)
    h.append("jid1", _user("u3"))
    messages = h.get("jid1")
    # At most max_pairs*2 + 1 messages (one incomplete pair)
    assert len(messages) <= h._max_pairs * 2 + 1


# ---------------------------------------------------------------------------
# Multiple JIDs isolated
# ---------------------------------------------------------------------------


def test_multiple_jids_are_isolated():
    h = InMemoryHistory()
    h.append("jid1", _user("from jid1"))
    h.append("jid2", _user("from jid2"))
    assert h.get("jid1")[0].content == "from jid1"
    assert h.get("jid2")[0].content == "from jid2"
    assert len(h.get("jid1")) == 1
    assert len(h.get("jid2")) == 1


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


def test_clear_removes_target_jid():
    h = InMemoryHistory()
    h.append("jid1", _user("hello"))
    h.clear("jid1")
    assert h.get("jid1") == []


def test_clear_does_not_affect_other_jids():
    h = InMemoryHistory()
    h.append("jid1", _user("hello"))
    h.append("jid2", _user("world"))
    h.clear("jid1")
    assert h.get("jid2")[0].content == "world"


def test_clear_unknown_jid_is_noop():
    h = InMemoryHistory()
    h.clear("ghost@s.whatsapp.net")  # must not raise


# ---------------------------------------------------------------------------
# sweep_idle
# ---------------------------------------------------------------------------


def test_sweep_idle_clears_timed_out_jid():
    now_counter = [0.0]

    def now_fn() -> float:
        return now_counter[0]

    h = InMemoryHistory(idle_timeout_seconds=60, now_fn=now_fn)
    h.append("jid1", _user("hi"))

    # Advance time beyond timeout
    now_counter[0] = 61.0
    cleared = h.sweep_idle()
    assert cleared == 1
    assert h.get("jid1") == []


def test_sweep_idle_does_not_clear_recent_jid():
    now_counter = [0.0]

    def now_fn() -> float:
        return now_counter[0]

    h = InMemoryHistory(idle_timeout_seconds=60, now_fn=now_fn)
    h.append("jid1", _user("hi"))

    now_counter[0] = 30.0  # within timeout
    cleared = h.sweep_idle()
    assert cleared == 0
    assert len(h.get("jid1")) == 1


def test_sweep_idle_returns_zero_when_empty():
    h = InMemoryHistory()
    assert h.sweep_idle() == 0


def test_sweep_idle_selectively_clears():
    now_counter = [0.0]

    def now_fn() -> float:
        return now_counter[0]

    h = InMemoryHistory(idle_timeout_seconds=60, now_fn=now_fn)
    h.append("jid1", _user("early"))

    now_counter[0] = 50.0
    h.append("jid2", _user("late"))

    now_counter[0] = 65.0  # jid1 is idle (65s), jid2 is fresh (15s)
    cleared = h.sweep_idle()
    assert cleared == 1
    assert h.get("jid1") == []
    assert len(h.get("jid2")) == 1


def test_sweep_idle_updates_last_active_on_append():
    """append() refreshes the last-active timestamp for the JID."""
    now_counter = [0.0]

    def now_fn() -> float:
        return now_counter[0]

    h = InMemoryHistory(idle_timeout_seconds=60, now_fn=now_fn)
    h.append("jid1", _user("first"))

    now_counter[0] = 50.0
    h.append("jid1", _user("refresh"))  # bumps last_active to 50.0

    now_counter[0] = 100.0  # 50s since last append — still within timeout
    cleared = h.sweep_idle()
    assert cleared == 0


def test_sweep_idle_at_exact_boundary_clears():
    """JID is cleared when elapsed == timeout (boundary inclusive)."""
    now_counter = [0.0]

    def now_fn() -> float:
        return now_counter[0]

    h = InMemoryHistory(idle_timeout_seconds=60, now_fn=now_fn)
    h.append("jid1", _user("hi"))

    now_counter[0] = 60.0  # exactly at timeout
    cleared = h.sweep_idle()
    assert cleared == 1
