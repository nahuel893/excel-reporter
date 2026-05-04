/**
 * Tests for SucursalSelectWidget.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { RJSFSchema } from "@rjsf/utils";
import { SucursalSelectWidget } from "../SucursalSelectWidget";

// Mock the queries module
vi.mock("@/lib/queries", () => ({
  useSucursales: () => ({
    data: ["CASA CENTRAL", "SUCURSAL CAFAYATE", "SUCURSAL METAN"],
    isLoading: false,
  }),
}));

function makeProps(overrides: Partial<Parameters<typeof SucursalSelectWidget>[0]> = {}) {
  return {
    id: "test-suc",
    name: "test-suc",
    value: [],
    required: false,
    disabled: false,
    readonly: false,
    autofocus: false,
    placeholder: "",
    label: "Sucursales",
    schema: { type: "array" } as RJSFSchema,
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
    multiple: true,
    ...overrides,
  };
}

function wrap(children: React.ReactNode) {
  const qc = new QueryClient();
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("SucursalSelectWidget", () => {
  it("renders checkboxes for each sucursal", () => {
    const props = makeProps();
    render(wrap(<SucursalSelectWidget {...props} />));
    expect(screen.getByTestId("sucursal-checkbox-CASA CENTRAL")).toBeInTheDocument();
    expect(screen.getByTestId("sucursal-checkbox-SUCURSAL CAFAYATE")).toBeInTheDocument();
    expect(screen.getByTestId("sucursal-checkbox-SUCURSAL METAN")).toBeInTheDocument();
  });

  it("shows checked state for selected values", () => {
    const props = makeProps({ value: ["CASA CENTRAL"] });
    render(wrap(<SucursalSelectWidget {...props} />));
    const checked = screen.getByTestId("sucursal-checkbox-CASA CENTRAL") as HTMLInputElement;
    expect(checked.checked).toBe(true);
    const unchecked = screen.getByTestId("sucursal-checkbox-SUCURSAL CAFAYATE") as HTMLInputElement;
    expect(unchecked.checked).toBe(false);
  });

  it("calls onChange with added item when checkbox is toggled on", () => {
    const onChange = vi.fn();
    const props = makeProps({ value: [], onChange });
    render(wrap(<SucursalSelectWidget {...props} />));
    fireEvent.click(screen.getByTestId("sucursal-checkbox-CASA CENTRAL"));
    expect(onChange).toHaveBeenCalledWith(["CASA CENTRAL"]);
  });

  it("calls onChange with removed item when checkbox is toggled off", () => {
    const onChange = vi.fn();
    const props = makeProps({ value: ["CASA CENTRAL", "SUCURSAL METAN"], onChange });
    render(wrap(<SucursalSelectWidget {...props} />));
    fireEvent.click(screen.getByTestId("sucursal-checkbox-CASA CENTRAL"));
    expect(onChange).toHaveBeenCalledWith(["SUCURSAL METAN"]);
  });
});
