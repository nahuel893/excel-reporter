/**
 * Tests for FilePathWidget.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { RJSFSchema } from "@rjsf/utils";
import { FilePathWidget } from "../FilePathWidget";
import * as apiModule from "@/lib/api";

// Minimal mock props
function makeProps(overrides: Partial<Parameters<typeof FilePathWidget>[0]> = {}) {
  return {
    id: "test-path",
    name: "test-path",
    value: "",
    required: false,
    disabled: false,
    readonly: false,
    autofocus: false,
    placeholder: "",
    label: "Plantilla",
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

describe("FilePathWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders a text input", () => {
    const props = makeProps();
    render(<FilePathWidget {...props} />);
    expect(screen.getByTestId("filepath-widget-test-path")).toBeInTheDocument();
  });

  it("shows gray dot initially (status unknown)", () => {
    const props = makeProps();
    render(<FilePathWidget {...props} />);
    const dot = screen.getByTestId("filepath-status-test-path");
    expect(dot.className).toContain("bg-gray-300");
  });

  it("shows green dot when path exists", async () => {
    vi.spyOn(apiModule.api.configs, "pathExists").mockResolvedValue({
      exists: true,
      is_file: true,
    });
    const props = makeProps({ value: "/some/path.xlsx" });
    render(<FilePathWidget {...props} />);
    const input = screen.getByTestId("filepath-widget-test-path");
    fireEvent.blur(input);
    await waitFor(() => {
      const dot = screen.getByTestId("filepath-status-test-path");
      expect(dot.className).toContain("bg-green-500");
    });
  });

  it("shows red dot when path does not exist", async () => {
    vi.spyOn(apiModule.api.configs, "pathExists").mockResolvedValue({
      exists: false,
      is_file: false,
    });
    const props = makeProps({ value: "/missing/path.xlsx" });
    render(<FilePathWidget {...props} />);
    const input = screen.getByTestId("filepath-widget-test-path");
    fireEvent.blur(input);
    await waitFor(() => {
      const dot = screen.getByTestId("filepath-status-test-path");
      expect(dot.className).toContain("bg-red-500");
    });
  });

  it("calls onChange when user types", () => {
    const onChange = vi.fn();
    const props = makeProps({ onChange });
    render(<FilePathWidget {...props} />);
    const input = screen.getByTestId("filepath-widget-test-path");
    fireEvent.change(input, { target: { value: "/new/path.xlsx" } });
    expect(onChange).toHaveBeenCalledWith("/new/path.xlsx");
  });
});
