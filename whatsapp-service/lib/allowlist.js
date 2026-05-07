/**
 * AllowlistManager — loads contacts from a JSON file and provides O(1) JID lookup.
 *
 * File format (subset of contactos_agente.json):
 *   { "contacts": [{ "jid": "549387...@s.whatsapp.net", ... }, ...] }
 *
 * On startup, reads the file. On reload(), re-reads and updates the in-memory Set.
 * If the file is missing or malformed, logs a warning and retains the previous state
 * (or stays empty on the first load).
 */

const fs = require("fs");
const pino = require("pino");

const logger = pino({ level: "info" });

class AllowlistManager {
  /**
   * @param {string} filePath — absolute path to contactos_agente.json
   */
  constructor(filePath) {
    this._filePath = filePath;
    /** @type {Set<string>} */
    this._jids = new Set();
    this._load(/* initial */ true);
  }

  /**
   * Returns true if the JID is in the allowlist.
   * @param {string} jid
   * @returns {boolean}
   */
  isAllowed(jid) {
    return this._jids.has(jid);
  }

  /**
   * Returns all JIDs currently in the allowlist.
   * @returns {string[]}
   */
  getJids() {
    return Array.from(this._jids);
  }

  /**
   * Re-reads the file from disk and updates the in-memory set.
   * On error, retains the previous set.
   */
  reload() {
    this._load(false);
  }

  /**
   * @private
   * @param {boolean} isInitial — true on constructor call (different log level)
   */
  _load(isInitial) {
    try {
      const raw = fs.readFileSync(this._filePath, "utf8");
      const data = JSON.parse(raw);
      const contacts = Array.isArray(data.contacts) ? data.contacts : [];
      const newSet = new Set(
        contacts
          .filter((c) => c && typeof c.jid === "string")
          .map((c) => c.jid)
      );
      this._jids = newSet;
      logger.info(
        { count: newSet.size, file: this._filePath },
        "Allowlist cargada"
      );
    } catch (err) {
      if (isInitial) {
        logger.warn(
          { err: err.message, file: this._filePath },
          "No se pudo cargar allowlist — inbound forwarding desactivado"
        );
        // Leave _jids as empty Set (already initialised in constructor)
      } else {
        logger.warn(
          { err: err.message, file: this._filePath },
          "Error al recargar allowlist — se conserva estado anterior"
        );
        // Retain previous _jids (no assignment)
      }
    }
  }
}

module.exports = { AllowlistManager };
