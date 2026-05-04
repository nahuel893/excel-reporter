/**
 * Tests for DateWidget.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { RJSFSchema } from "@rjsf/utils";
import { DateWidget } from "../DateWidget";

// Minimal mock props for WidgetProps
function makeProps(overrides: Partial<Parameters<typeof DateWidget>[0]> = {}) {
  return {
    id: "test-date",
    name: "test-date",
    value: "",
    required: false,
    disabled: false,
    readonly: false,
    autofocus: false,
    placeholder: "",
    label: "Fecha",
    schema: { type: "string" } as RJSFSchema,
    uiSchema: {},
    options: {},
    onChange: vi.fn(),
    onBlur: vi.fn(),
    onFocus: vi.fn(),
    formContext: {},
    rawErrors: [],
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    registry: {} as any,
    hideLabel: false,
    hideError: false,
    multiple: false,
    ...overrides,
  };
}

describe("DateWidget", () => {
  it("renders a date input with the current value", () => {
    const props = makeProps({ value: "2026-05-04" });
    render(<DateWidget {...props} />);
    const input = screen.getByTestId("date-widget-test-date") as HTMLInputElement;
    expect(input.type).toBe("date");
    expect(input.value).toBe("2026-05-04");
  });

  it("calls onChange with the new value when changed", () => {
    const onChange = vi.fn();
    const props = makeProps({ onChange });
    render(<DateWidget {...props} />);
    const input = screen.getByTestId("date-widget-test-date");
    fireEvent.change(input, { target: { value: "2026-06-01" } });
    expect(onChange).toHaveBeenCalledWith("2026-06-01");
  });

  it("calls onChange with undefined when cleared", () => {
    const onChange = vi.fn();
    const props = makeProps({ value: "2026-05-04", onChange });
    render(<DateWidget {...props} />);
    const input = screen.getByTestId("date-widget-test-date");
    fireEvent.change(input, { target: { value: "" } });
    expect(onChange).toHaveBeenCalledWith(undefined);
  });

  it("is disabled when disabled prop is true", () => {
    const props = makeProps({ disabled: true });
    render(<DateWidget {...props} />);
    const input = screen.getByTestId("date-widget-test-date") as HTMLInputElement;
    expect(input.disabled).toBe(true);
  });

  it("is disabled when readonly prop is true", () => {
    const props = makeProps({ readonly: true });
    render(<DateWidget {...props} />);
    const input = screen.getByTestId("date-widget-test-date") as HTMLInputElement;
    expect(input.disabled).toBe(true);
  });
});
