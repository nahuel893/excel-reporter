/**
 * Tests for lib/schema.ts — uiSchema builder from JSON Schema x-widget extensions.
 *
 * TDD: RED → GREEN → TRIANGULATE → REFACTOR
 */

import { describe, it, expect } from "vitest";
import { buildUiSchema, getXWidget } from "../schema";

// ─── Test fixtures ────────────────────────────────────────────────────────────

const flatSchema = {
  type: "object",
  properties: {
    fecha_desde: {
      type: "string",
      "x-widget": "date",
    },
    archivo_plantilla: {
      type: "string",
      "x-widget": "filepath",
    },
    sucursales: {
      type: "array",
      "x-widget": "sucursal-select-array",
      items: { type: "string" },
    },
    nombre: {
      type: "string",
      // No x-widget — should NOT appear in uiSchema
    },
  },
};

const nestedSchema = {
  type: "object",
  $defs: {
    ReportFilters: {
      type: "object",
      properties: {
        fecha_desde: {
          type: "string",
          "x-widget": "date",
        },
        supervisores: {
          type: "object",
          "x-widget": "supervisor-matrix",
          additionalProperties: {
            type: "array",
            items: { type: "string" },
          },
        },
        categorias: {
          type: "object",
          "x-widget": "json-editor",
          additionalProperties: true,
        },
      },
    },
  },
  properties: {
    filtros: {
      $ref: "#/$defs/ReportFilters",
    },
    nombre: {
      type: "string",
    },
  },
};

const allOfSchema = {
  type: "object",
  $defs: {
    Base: {
      type: "object",
      properties: {
        fecha_desde: {
          type: "string",
          "x-widget": "date",
        },
      },
    },
  },
  allOf: [{ $ref: "#/$defs/Base" }],
};

// ─── buildUiSchema tests ──────────────────────────────────────────────────────

describe("buildUiSchema", () => {
  it("maps x-widget: date to ui:widget DateWidget on a flat schema", () => {
    const ui = buildUiSchema(flatSchema);
    expect(ui["fecha_desde"]).toEqual({ "ui:widget": "DateWidget" });
  });

  it("maps x-widget: filepath to FilePathWidget", () => {
    const ui = buildUiSchema(flatSchema);
    expect(ui["archivo_plantilla"]).toEqual({ "ui:widget": "FilePathWidget" });
  });

  it("maps x-widget: sucursal-select-array to SucursalSelectWidget", () => {
    const ui = buildUiSchema(flatSchema);
    expect(ui["sucursales"]).toEqual({ "ui:widget": "SucursalSelectWidget" });
  });

  it("does NOT include entries for fields without x-widget", () => {
    const ui = buildUiSchema(flatSchema);
    expect(ui["nombre"]).toBeUndefined();
  });

  it("resolves $ref to $defs and maps x-widget on nested fields", () => {
    const ui = buildUiSchema(nestedSchema);
    // filtros is a $ref — should resolve and include its children
    const filtrosUi = ui["filtros"] as Record<string, unknown>;
    expect(filtrosUi).toBeDefined();
    expect(filtrosUi["fecha_desde"]).toEqual({ "ui:widget": "DateWidget" });
  });

  it("maps supervisor-matrix widget via $ref resolution", () => {
    const ui = buildUiSchema(nestedSchema);
    const filtrosUi = ui["filtros"] as Record<string, unknown>;
    expect(filtrosUi["supervisores"]).toEqual({ "ui:widget": "SupervisorMatrixWidget" });
  });

  it("maps json-editor widget via $ref resolution", () => {
    const ui = buildUiSchema(nestedSchema);
    const filtrosUi = ui["filtros"] as Record<string, unknown>;
    expect(filtrosUi["categorias"]).toEqual({ "ui:widget": "JsonEditorWidget" });
  });

  it("handles allOf with $ref resolution", () => {
    const ui = buildUiSchema(allOfSchema);
    expect(ui["fecha_desde"]).toEqual({ "ui:widget": "DateWidget" });
  });

  it("ignores unknown x-widget values gracefully", () => {
    const schema = {
      type: "object",
      properties: {
        field: {
          type: "string",
          "x-widget": "unknown-future-widget",
        },
      },
    };
    const ui = buildUiSchema(schema);
    // Unknown widget → no ui:widget entry
    expect(ui["field"]).toBeUndefined();
  });

  it("returns empty object for schema with no x-widget extensions", () => {
    const schema = {
      type: "object",
      properties: {
        a: { type: "string" },
        b: { type: "number" },
      },
    };
    expect(buildUiSchema(schema)).toEqual({});
  });
});

// ─── getXWidget tests ─────────────────────────────────────────────────────────

describe("getXWidget", () => {
  it("returns x-widget value for a direct property", () => {
    expect(getXWidget(flatSchema, "fecha_desde")).toBe("date");
  });

  it("returns undefined for a property without x-widget", () => {
    expect(getXWidget(flatSchema, "nombre")).toBeUndefined();
  });

  it("returns undefined for a non-existent path", () => {
    expect(getXWidget(flatSchema, "nonexistent.path")).toBeUndefined();
  });

  it("resolves nested path through $ref", () => {
    expect(getXWidget(nestedSchema, "filtros.fecha_desde")).toBe("date");
  });

  it("resolves supervisor-matrix through $ref path", () => {
    expect(getXWidget(nestedSchema, "filtros.supervisores")).toBe("supervisor-matrix");
  });
});
