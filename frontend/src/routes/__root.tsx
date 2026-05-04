/**
 * Root route layout — sidebar + topbar + <Outlet />
 */

import { createRootRoute, Link, Outlet } from "@tanstack/react-router";
import { useActiveRuns } from "@/lib/queries";
import { cn } from "@/lib/utils";

function RootLayout() {
  const { data: activeRuns } = useActiveRuns();
  const activeCount = activeRuns?.items?.length ?? 0;

  const navItems = [
    { to: "/", label: "Dashboard", icon: "⊞" },
    { to: "/configs", label: "Configuraciones", icon: "⚙" },
    { to: "/runs", label: "Ejecuciones", icon: "▶" },
    { to: "/schedule", label: "Programación", icon: "🕐" },
    { to: "/artifacts", label: "Archivos", icon: "📁" },
    { to: "/contactos", label: "Contactos", icon: "👤" },
  ];

  return (
    <div className="flex min-h-screen bg-background">
      {/* Sidebar */}
      <aside className="flex w-56 flex-shrink-0 flex-col border-r border-border bg-card">
        <div className="flex h-14 items-center border-b border-border px-4">
          <span className="text-sm font-semibold text-foreground">
            Informes Badie
          </span>
          {activeCount > 0 && (
            <span
              className="ml-auto flex h-5 w-5 items-center justify-center rounded-full bg-primary text-xs text-primary-foreground"
              title={`${activeCount} ejecución(es) activa(s)`}
              data-testid="active-runs-badge"
            >
              {activeCount}
            </span>
          )}
        </div>
        <nav className="flex flex-1 flex-col gap-1 p-2" aria-label="Navegación principal">
          {navItems.map((item) => (
            <Link
              key={item.to}
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              to={item.to as any}
              className={cn(
                "flex items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground",
              )}
              activeProps={{ className: "bg-accent text-accent-foreground font-medium" }}
            >
              <span aria-hidden="true">{item.icon}</span>
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="border-t border-border p-3 text-xs text-muted-foreground">
          v2.0
        </div>
      </aside>

      {/* Main content */}
      <main className="flex flex-1 flex-col overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}

export const rootRoute = createRootRoute({
  component: RootLayout,
});
