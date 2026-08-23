/**
 * Tests for routes/artifacts.tsx — three-level artifacts browser (Unit 11).
 *
 * TDD: written BEFORE implementation.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import type {
  ArtifactFileEntry,
  ArtifactTree,
} from "@/lib/queries";

const useArtifactTreeMock = vi.fn();

vi.mock("@/lib/queries", () => ({
  useArtifactTree: (slug?: string, periodo?: string) =>
    useArtifactTreeMock(slug, periodo),
}));

// Import AFTER the mock is registered.
import { ArtifactsPage } from "../artifacts";

function queryResult(data: ArtifactTree | undefined, isLoading = false) {
  return { data, isLoading, isError: false, error: null };
}

function queryError(error: unknown) {
  return { data: undefined, isLoading: false, isError: true, error };
}

const rootTree: ArtifactTree = {
  services: [
    { slug: "ventas", periods: [], unreadable: false },
    { slug: "resumen-mensual", periods: [], unreadable: false },
  ],
  unclassified: [
    {
      name: "loose.xlsx",
      path: "loose.xlsx",
      kind: "xlsx",
      size_bytes: 1024,
      mtime: "2026-08-01T00:00:00+00:00",
    },
  ],
};

const ventasPeriods: ArtifactTree = {
  services: [
    {
      slug: "ventas",
      unreadable: false,
      periods: [
        { periodo: "2026-07", anomalous: false,
          unreadable: false, principal: [], imagenes: [], backups: [] },
      ],
    },
  ],
  unclassified: [],
};

const contaminatedPeriods: ArtifactTree = {
  services: [
    {
      slug: "resumen-mensual",
      unreadable: false,
      periods: [
        {
          periodo: "2026-06.contaminated",
          anomalous: true,
          unreadable: false,
          principal: [],
          imagenes: [],
          backups: [],
        },
      ],
    },
  ],
  unclassified: [],
};

const principalFile: ArtifactFileEntry = {
  name: "Ventas Test.xlsx",
  path: "ventas/2026-07/Ventas Test.xlsx",
  kind: "xlsx",
  size_bytes: 2048,
  mtime: "2026-07-15T10:00:00+00:00",
};

const imageFile: ArtifactFileEntry = {
  name: "Ventas Test_Hoja1_A1_D10.png",
  path: "ventas/2026-07/Ventas Test_Hoja1_A1_D10.png",
  kind: "png",
  size_bytes: 512,
  mtime: "2026-07-15T10:00:00+00:00",
  sheet: "Hoja1",
  range: "A1:D10",
};

const backupFile: ArtifactFileEntry = {
  name: "Ventas Test_backup.xlsx",
  path: "ventas/2026-07/Ventas Test_backup.xlsx",
  kind: "xlsx",
  size_bytes: 2000,
  mtime: "2026-07-15T09:00:00+00:00",
};

const ventasJulyFiles: ArtifactTree = {
  services: [
    {
      slug: "ventas",
      unreadable: false,
      periods: [
        {
          periodo: "2026-07",
          anomalous: false,
          unreadable: false,
          principal: [principalFile],
          imagenes: [imageFile],
          backups: [backupFile],
        },
      ],
    },
  ],
  unclassified: [],
};

describe("ArtifactsPage", () => {
  beforeEach(() => {
    useArtifactTreeMock.mockReset();
  });

  it("renders an honest empty state when the tree has no services and no loose files", () => {
    useArtifactTreeMock.mockReturnValue(
      queryResult({ services: [], unclassified: [] }),
    );
    render(<ArtifactsPage />);
    expect(screen.getByTestId("artifacts-empty")).toBeInTheDocument();
  });

  it("renders a loading indicator while the tree is being fetched", () => {
    useArtifactTreeMock.mockReturnValue(queryResult(undefined, true));
    render(<ArtifactsPage />);
    expect(screen.getByTestId("artifacts-loading")).toBeInTheDocument();
  });

  it("lists services and a warning-flagged 'unclassified' bucket at the root level", () => {
    useArtifactTreeMock.mockReturnValue(queryResult(rootTree));
    render(<ArtifactsPage />);
    expect(screen.getByTestId("service-card-ventas")).toBeInTheDocument();
    expect(screen.getByTestId("service-card-resumen-mensual")).toBeInTheDocument();
    expect(screen.getByTestId("unclassified-card")).toBeInTheDocument();
  });

  it("drills into a service to show its periods, flagging anomalous folders", () => {
    useArtifactTreeMock.mockImplementation((slug?: string) => {
      if (slug === "resumen-mensual") return queryResult(contaminatedPeriods);
      return queryResult(rootTree);
    });
    render(<ArtifactsPage />);

    fireEvent.click(screen.getByTestId("service-card-resumen-mensual"));

    const periodCard = screen.getByTestId("period-card-2026-06.contaminated");
    expect(periodCard).toBeInTheDocument();
    expect(within(periodCard).getByText(/anómala/i)).toBeInTheDocument();
  });

  it("says a period could not be read instead of showing it as empty", () => {
    const unreadablePeriod: ArtifactTree = {
      services: [
        {
          slug: "ventas",
          unreadable: false,
          periods: [
            {
              periodo: "2026-07",
              anomalous: false,
              unreadable: true,
              principal: [],
              imagenes: [],
              backups: [],
            },
          ],
        },
      ],
      unclassified: [],
    };
    useArtifactTreeMock.mockImplementation((slug?: string) => {
      if (slug === "ventas") return queryResult(unreadablePeriod);
      return queryResult(rootTree);
    });
    render(<ArtifactsPage />);

    fireEvent.click(screen.getByTestId("service-card-ventas"));

    const periodCard = screen.getByTestId("period-card-2026-07");
    expect(within(periodCard).getByText(/no se pudo leer/i)).toBeInTheDocument();
  });

  it("says the list could not be read instead of 'no hay archivos generados'", () => {
    // A backend that cannot be reached must never look like a backend that
    // reported an empty data/output/.
    useArtifactTreeMock.mockReturnValue(queryError(new Error("Network down")));
    render(<ArtifactsPage />);

    expect(screen.getByTestId("artifacts-error")).toBeInTheDocument();
    expect(screen.queryByTestId("artifacts-empty")).not.toBeInTheDocument();
    expect(screen.getByText(/network down/i)).toBeInTheDocument();
  });

  it("says the selected period is missing instead of showing the root grid", () => {
    useArtifactTreeMock.mockImplementation((slug?: string, periodo?: string) => {
      // Server answers without the period the breadcrumb points at.
      if (slug === "ventas" && periodo === "2026-07") {
        return queryResult({
          services: [{ slug: "ventas", periods: [], unreadable: false }],
          unclassified: [],
        });
      }
      if (slug === "ventas") return queryResult(ventasPeriods);
      return queryResult(rootTree);
    });
    render(<ArtifactsPage />);

    fireEvent.click(screen.getByTestId("service-card-ventas"));
    fireEvent.click(screen.getByTestId("period-card-2026-07"));

    expect(screen.getByTestId("period-missing")).toBeInTheDocument();
    expect(screen.queryByTestId("service-card-resumen-mensual")).not.toBeInTheDocument();
  });

  it("says the selected service is missing instead of showing the root grid", () => {
    useArtifactTreeMock.mockImplementation((slug?: string) => {
      // Server answers without the service the breadcrumb points at.
      if (slug === "ventas") return queryResult({ services: [], unclassified: [] });
      return queryResult(rootTree);
    });
    render(<ArtifactsPage />);

    fireEvent.click(screen.getByTestId("service-card-ventas"));

    expect(screen.getByTestId("service-missing")).toBeInTheDocument();
    expect(screen.queryByTestId("artifacts-empty")).not.toBeInTheDocument();
    expect(screen.queryByTestId("service-card-resumen-mensual")).not.toBeInTheDocument();
  });

  it("says a whole service could not be read instead of 'sin períodos'", () => {
    const unreadableService: ArtifactTree = {
      services: [{ slug: "ventas", periods: [], unreadable: true }],
      unclassified: [],
    };
    useArtifactTreeMock.mockImplementation((slug?: string) => {
      if (slug === "ventas") return queryResult(unreadableService);
      return queryResult(rootTree);
    });
    render(<ArtifactsPage />);

    fireEvent.click(screen.getByTestId("service-card-ventas"));

    expect(screen.getByText(/no se pudo leer la carpeta/i)).toBeInTheDocument();
    expect(screen.queryByText(/sin períodos/i)).not.toBeInTheDocument();
  });

  it("drills into a period to show principal/imagenes/backups with inline PNG preview and download links", () => {
    useArtifactTreeMock.mockImplementation((slug?: string, periodo?: string) => {
      if (slug === "ventas" && periodo === "2026-07") return queryResult(ventasJulyFiles);
      if (slug === "ventas") return queryResult(ventasPeriods);
      return queryResult(rootTree);
    });
    render(<ArtifactsPage />);

    fireEvent.click(screen.getByTestId("service-card-ventas"));
    fireEvent.click(screen.getByTestId("period-card-2026-07"));

    // Principal file: download link, not inline preview.
    const principalLink = screen.getByTestId(
      "download-link-ventas/2026-07/Ventas Test.xlsx",
    ) as HTMLAnchorElement;
    expect(principalLink.href).toContain(
      "/mgmt/artifacts/file?path=" + encodeURIComponent(principalFile.path),
    );

    // Image file: inline <img> preview, labeled with parsed sheet + range.
    const preview = screen.getByTestId(
      "image-preview-ventas/2026-07/Ventas Test_Hoja1_A1_D10.png",
    ) as HTMLImageElement;
    expect(preview.src).toContain(
      "/mgmt/artifacts/file?path=" + encodeURIComponent(imageFile.path),
    );
    expect(screen.getByText(/Hoja1/)).toBeInTheDocument();
    expect(screen.getByText(/A1:D10/)).toBeInTheDocument();

    // Backup file: still listed, downloadable.
    expect(
      screen.getByTestId("download-link-ventas/2026-07/Ventas Test_backup.xlsx"),
    ).toBeInTheDocument();
  });

  it("shows the loose root files when the 'unclassified' bucket is selected", () => {
    useArtifactTreeMock.mockReturnValue(queryResult(rootTree));
    render(<ArtifactsPage />);

    fireEvent.click(screen.getByTestId("unclassified-card"));

    expect(screen.getByTestId("download-link-loose.xlsx")).toBeInTheDocument();
  });
});
