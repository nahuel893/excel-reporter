/**
 * ConfigForm — rjsf Form with custom widget registry + uiSchema injection.
 *
 * Receives the JSON Schema (with x-widget extensions from the server) and
 * the current config content. Builds a uiSchema via lib/schema.ts and
 * renders rjsf <Form/> with all 5 custom widgets registered.
 */

import Form from "@rjsf/core";
import validator from "@rjsf/validator-ajv8";
import type { IChangeEvent } from "@rjsf/core";
import type { RJSFSchema, ErrorSchema } from "@rjsf/utils";
import { buildUiSchema } from "@/lib/schema";
import { widgetRegistry } from "@/widgets";
import { cn } from "@/lib/utils";

interface FieldError {
  loc: string[];
  msg: string;
  type: string;
}

interface ConfigFormProps {
  schema: Record<string, unknown>;
  formData: Record<string, unknown>;
  onChange?: (data: Record<string, unknown>) => void;
  onSubmit: (data: Record<string, unknown>) => void;
  serverErrors?: FieldError[];
  isSaving?: boolean;
  submitLabel?: string;
}

export function ConfigForm({
  schema,
  formData,
  onChange,
  onSubmit,
  serverErrors,
  isSaving = false,
  submitLabel = "Guardar",
}: ConfigFormProps) {
  const uiSchema = buildUiSchema(schema as Parameters<typeof buildUiSchema>[0]);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const handleSubmit = (data: IChangeEvent<any>) => {
    if (data.formData) {
      onSubmit(data.formData as Record<string, unknown>);
    }
  };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const handleChange = (data: IChangeEvent<any>) => {
    if (onChange && data.formData) {
      onChange(data.formData as Record<string, unknown>);
    }
  };

  // Convert server 422 errors to rjsf extraErrors format
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const extraErrors: ErrorSchema<any> = {};
  if (serverErrors) {
    for (const err of serverErrors) {
      if (err.loc.length > 0) {
        const key = err.loc.join(".");
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        if (!(extraErrors as any)[key]) {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          (extraErrors as any)[key] = { __errors: [] };
        }
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        ((extraErrors as any)[key] as { __errors: string[] }).__errors.push(err.msg);
      }
    }
  }

  return (
    <div className="config-form" data-testid="config-form">
      <Form
        schema={schema as RJSFSchema}
        uiSchema={uiSchema}
        formData={formData}
        validator={validator}
        widgets={widgetRegistry}
        onChange={handleChange}
        onSubmit={handleSubmit}
        extraErrors={extraErrors}
        showErrorList={serverErrors && serverErrors.length > 0 ? "top" : false}
      >
        <div className="mt-4 flex gap-2">
          <button
            type="submit"
            disabled={isSaving}
            className={cn(
              "rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow hover:bg-primary/90 focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
            )}
            data-testid="config-form-submit"
          >
            {isSaving ? "Guardando..." : submitLabel}
          </button>
        </div>
      </Form>
    </div>
  );
}
