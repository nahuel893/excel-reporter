/**
 * MessageDeduplicator — per-JID idempotency store keyed by (jid, ts).
 *
 * Baileys can re-emit the same message.upsert event. This module tracks seen
 * (jid, ts) pairs within a sliding time window (default: 60 seconds).
 *
 * Storage: Map<jid, Map<ts, recordedAt>> — all values in Unix seconds.
 *
 * isDuplicate(jid, ts):
 *   - Prunes expired entries first.
 *   - If (jid, ts) is already in the store → returns true.
 *   - Otherwise records it and returns false.
 *
 * prune(): manually removes all entries older than windowSec.
 *          Called automatically inside isDuplicate().
 */

class MessageDeduplicator {
  /**
   * @param {number} windowSec — how long (in seconds) to remember a (jid, ts) pair
   */
  constructor(windowSec = 60) {
    this._windowSec = windowSec;
    /** @type {Map<string, Map<number, number>>} jid → (ts → recordedAt) */
    this._store = new Map();
  }

  /**
   * @param {string} jid
   * @param {number} ts — Unix timestamp in seconds (from Baileys messageTimestamp)
   * @returns {boolean} true if this (jid, ts) was already seen within the window
   */
  isDuplicate(jid, ts) {
    this.prune();

    if (!this._store.has(jid)) {
      this._store.set(jid, new Map());
    }

    const jidMap = this._store.get(jid);
    const nowSec = Math.floor(Date.now() / 1000);

    if (jidMap.has(ts)) {
      return true;
    }

    jidMap.set(ts, nowSec);
    return false;
  }

  /**
   * Removes entries older than windowSec from the store.
   * Called automatically by isDuplicate(); can also be called manually.
   */
  prune() {
    const cutoff = Math.floor(Date.now() / 1000) - this._windowSec;

    for (const [jid, jidMap] of this._store.entries()) {
      for (const [ts, recordedAt] of jidMap.entries()) {
        if (recordedAt <= cutoff) {
          jidMap.delete(ts);
        }
      }
      if (jidMap.size === 0) {
        this._store.delete(jid);
      }
    }
  }
}

module.exports = { MessageDeduplicator };
