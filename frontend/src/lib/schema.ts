/**
 * JSON Schema x-widget extension reader → rjsf uiSchema builder.
 *
 * The server injects `x-widget` extensions on specific fields in the JSON
 * Schema. This module walks the schema and builds an rjsf-compatible
 * `uiSchema` object that maps `"ui:widget"` keys to our custom widget names.
 *
 * x-widget values and their widget names:
 *   date                    → DateWidget
 *   filepath                → FilePathWidget
 *   sucursal-select-array   → SucursalSelectWidget
 *   generico-select-array   → GenericoSelectWidget
 *   supervisor-matrix       → SupervisorMatrixWidget
 *   json-editor             → JsonEditorWidget
 */

export type XWidget =
  | "date"
  | "filepath"
  | "sucursal-select-array"
  | "generico-select-array"
  | "supervisor-matrix"
  | "json-editor";

// Map x-widget value → rjsf ui:widget name (must match widgets registry keys)
const WIDGET_MAP: Record<XWidget, string> = {
  date: "DateWidget",
  filepath: "FilePathWidget",
  "sucursal-select-array": "SucursalSelectWidget",
  "generico-select-array": "GenericoSelectWidget",
  "supervisor-matrix": "SupervisorMatrixWidget",
  "json-editor": "JsonEditorWidget",
};

type JsonSchemaNode = {
  "x-widget"?: string;
  properties?: Record<string, JsonSchemaNode>;
  // items can be a partial schema node (e.g. just {type: "string"} in tests)
  items?: Partial<JsonSchemaNode> & { type?: string };
  $defs?: Record<string, JsonSchemaNode>;
  $ref?: string;
  allOf?: JsonSchemaNode[];
  anyOf?: JsonSchemaNode[];
  oneOf?: JsonSchemaNode[];
  // Allow extra JSON Schema keywords to pass through
  [key: string]: unknown;
};

type UiSchema = {
  [key: string]: unknown;
};

/**
 * Build an rjsf uiSchema from a JSON Schema by walking `x-widget`
 * extensions. The schema may contain `$defs` with `$ref` pointers;
 * we resolve those inline.
 *
 * @param schema - The augmented JSON Schema from the server
 * @returns rjsf-compatible uiSchema
 */
export function buildUiSchema(schema: JsonSchemaNode): UiSchema {
  // Collect $defs for $ref resolution
  const defs: Record<string, JsonSchemaNode> = schema.$defs ?? {};
  return walkNode(schema, defs);
}

function resolveRef(ref: string, defs: Record<string, JsonSchemaNode>): JsonSchemaNode | null {
  // Only handle local $defs refs: "#/$defs/ModelName"
  const match = ref.match(/^#\/\$defs\/(.+)$/);
  if (!match) return null;
  return defs[match[1]] ?? null;
}

function walkNode(
  node: JsonSchemaNode,
  defs: Record<string, JsonSchemaNode>,
): UiSchema {
  const uiSchema: UiSchema = {};

  // Resolve $ref if present
  let resolved = node;
  if (node.$ref) {
    const deref = resolveRef(node.$ref, defs);
    if (deref) {
      resolved = { ...deref, ...node }; // node fields take priority (e.g. x-widget)
    }
  }

  // Handle allOf/anyOf/oneOf: merge the first match that has properties
  for (const combiner of ["allOf", "anyOf", "oneOf"] as const) {
    const branches = resolved[combiner];
    if (branches) {
      for (const branch of branches) {
        const sub = walkNode(branch, defs);
        Object.assign(uiSchema, sub);
      }
    }
  }

  // Apply x-widget at this level
  const xWidget = resolved["x-widget"];
  if (xWidget && xWidget in WIDGET_MAP) {
    uiSchema["ui:widget"] = WIDGET_MAP[xWidget as XWidget];
  }

  // Walk properties recursively
  if (resolved.properties) {
    for (const [key, childSchema] of Object.entries(resolved.properties)) {
      const childUi = walkNode(childSchema, defs);
      if (Object.keys(childUi).length > 0) {
        uiSchema[key] = childUi;
      }
    }
  }

  // Walk items (array items)
  if (resolved.items) {
    const itemsUi = walkNode(resolved.items as JsonSchemaNode, defs);
    if (Object.keys(itemsUi).length > 0) {
      uiSchema["items"] = itemsUi;
    }
  }

  return uiSchema;
}

/**
 * Extract the x-widget value from a specific field path in the schema.
 * Used by tests to verify server-injected widget extensions.
 *
 * @param schema - The root JSON Schema
 * @param path - Dot-separated field path, e.g. "filtros.fecha_desde"
 * @returns The x-widget value or undefined
 */
export function getXWidget(
  schema: JsonSchemaNode,
  path: string,
): string | undefined {
  const defs: Record<string, JsonSchemaNode> = schema.$defs ?? {};
  const parts = path.split(".");
  let current: JsonSchemaNode | null = schema;

  for (const part of parts) {
    if (!current) return undefined;

    // Resolve $ref
    if (current.$ref) {
      current = resolveRef(current.$ref, defs);
      if (!current) return undefined;
    }

    // Resolve allOf/anyOf/oneOf by looking in each branch
    for (const combiner of ["allOf", "anyOf", "oneOf"] as const) {
      const branches = current[combiner];
      if (branches) {
        for (const branch of branches) {
          let resolved: JsonSchemaNode = branch;
          if (branch.$ref) {
            resolved = resolveRef(branch.$ref, defs) ?? branch;
          }
          if (resolved.properties?.[part]) {
            current = { properties: {} };
            for (const b of branches) {
              let rb: JsonSchemaNode = b;
              if (b.$ref) {
                rb = resolveRef(b.$ref, defs) ?? b;
              }
              if (rb.properties) {
                (current.properties as Record<string, JsonSchemaNode>)[part] =
                  rb.properties[part] ?? (current.properties as Record<string, JsonSchemaNode>)[part];
              }
            }
            break;
          }
        }
      }
    }

    if (current.properties?.[part]) {
      current = current.properties[part];
    } else {
      return undefined;
    }
  }

  if (!current) return undefined;

  // Resolve final $ref
  if (current.$ref) {
    current = resolveRef(current.$ref, defs);
  }

  return current?.["x-widget"];
}
