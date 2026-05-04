/**
 * Root route layout — sidebar + <Outlet />
 * Dark sidebar with violet accent, lucide icons, active-link indicator.
 */

import { createRootRoute, Link, Outlet, useRouterState } from "@tanstack/react-router";
import {
  LayoutDashboard,
  Settings2,
  Play,
  CalendarClock,
  Folder,
  Users,
} from "lucide-react";
import { useActiveRuns } from "@/lib/queries";
import { cn } from "@/lib/utils";

type NavItem = {
  to: string;
  label: string;
  icon: React.ReactNode;
};

const navItems: NavItem[] = [
  { to: "/", label: "Dashboard", icon: <LayoutDashboard size={16} /> },
  { to: "/configs", label: "Configuraciones", icon: <Settings2 size={16} /> },
  { to: "/runs", label: "Ejecuciones", icon: <Play size={16} /> },
  { to: "/schedule", label: "Programación", icon: <CalendarClock size={16} /> },
  { to: "/artifacts", label: "Archivos", icon: <Folder size={16} /> },
  { to: "/contactos", label: "Contactos", icon: <Users size={16} /> },
];

function ActiveRunsBadge({ count }: { count: number }) {
  if (count === 0) return null;
  return (
    <span
      className="badge-pulse ml-auto flex h-5 min-w-[20px] items-center justify-center rounded-full bg-primary px-1 text-[11px] font-semibold text-primary-foreground"
      title={`${count} ejecución(es) activa(s)`}
      data-testid="active-runs-badge"
    >
      {count}
    </span>
  );
}

function NavLink({ item }: { item: NavItem }) {
  const routerState = useRouterState();
  const pathname = routerState.location.pathname;

  // Consider "/" active only on exact match; others on prefix
  const isActive =
    item.to === "/"
      ? pathname === "/" || pathname === ""
      : pathname.startsWith(item.to);

  return (
    <Link
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      to={item.to as any}
      className={cn(
        "nav-active-indicator relative flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors duration-150",
        isActive
          ? "bg-accent text-foreground font-medium"
          : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
      )}
      aria-current={isActive ? "page" : undefined}
    >
      <span
        className={cn(
          "transition-colors duration-150",
          isActive ? "text-primary" : "text-muted-foreground",
        )}
        aria-hidden="true"
      >
        {item.icon}
      </span>
      {item.label}
    </Link>
  );
}

function RootLayout() {
  const { data: activeRuns } = useActiveRuns();
  const activeCount = activeRuns?.items?.length ?? 0;

  return (
    <div className="flex min-h-screen bg-background">
      {/* Sidebar */}
      <aside className="flex w-56 flex-shrink-0 flex-col border-r border-border bg-card">
        {/* Logo / brand */}
        <div className="flex h-14 items-center gap-3 border-b border-border px-4">
          <div
            className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-[11px] font-bold tracking-tight text-primary-foreground"
            aria-hidden="true"
          >
            IB
          </div>
          <span className="text-sm font-semibold tracking-tight text-foreground">
            Informes Badie
          </span>
          <ActiveRunsBadge count={activeCount} />
        </div>

        {/* Nav */}
        <nav
          className="flex flex-1 flex-col gap-0.5 p-2 pt-3"
          aria-label="Navegación principal"
        >
          {navItems.map((item) => (
            <NavLink key={item.to} item={item} />
          ))}
        </nav>

        {/* Version footer */}
        <div className="border-t border-border px-4 py-3 text-[11px] text-muted-foreground/60">
          v2.0.0
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
