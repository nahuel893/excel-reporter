/**
 * rjsf custom widgets registry.
 *
 * Import this and pass as the `widgets` prop to <Form />.
 */

export { DateWidget } from "./DateWidget";
export { FilePathWidget } from "./FilePathWidget";
export { SucursalSelectWidget } from "./SucursalSelectWidget";
export { GenericoSelectWidget } from "./GenericoSelectWidget";
export { SupervisorMatrixWidget } from "./SupervisorMatrixWidget";
export { JsonEditorWidget } from "./JsonEditorWidget";

import { DateWidget } from "./DateWidget";
import { FilePathWidget } from "./FilePathWidget";
import { SucursalSelectWidget } from "./SucursalSelectWidget";
import { GenericoSelectWidget } from "./GenericoSelectWidget";
import { SupervisorMatrixWidget } from "./SupervisorMatrixWidget";
import { JsonEditorWidget } from "./JsonEditorWidget";

/**
 * Registry object to pass to rjsf <Form widgets={widgetRegistry} />.
 * Keys must match the values in WIDGET_MAP in lib/schema.ts.
 */
export const widgetRegistry = {
  DateWidget,
  FilePathWidget,
  SucursalSelectWidget,
  GenericoSelectWidget,
  SupervisorMatrixWidget,
  JsonEditorWidget,
};
