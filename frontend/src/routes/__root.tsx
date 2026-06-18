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
  Zap,
} from "lucide-react";
import { useActiveRuns, useConfigs } from "@/lib/queries";
import { cn } from "@/lib/utils";

type NavItem = {
  to: string;
  label: string;
  icon: React.ReactNode;
  countLoader?: () => number;
};

const navItems: NavItem[] = [
  { to: "/", label: "Dashboard", icon: <LayoutDashboard size={16} /> },
  { to: "/configs", label: "Configuraciones", icon: <Settings2 size={16} /> },
  { to: "/runs", label: "Ejecuciones", icon: <Play size={16} /> },
  { to: "/schedule", label: "Programación", icon: <CalendarClock size={16} /> },
  { to: "/artifacts", label: "Archivos", icon: <Folder size={16} /> },
  { to: "/contactos", label: "Contactos", icon: <Users size={16} /> },
];

function NavLink({ item }: { item: NavItem }) {
  const routerState = useRouterState();
  const pathname = routerState.location.pathname;

  const isActive =
    item.to === "/"
      ? pathname === "/" || pathname === ""
      : pathname.startsWith(item.to);

  return (
    <Link
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      to={item.to as any}
      className={cn(
        "nav-active-indicator group relative flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-all duration-150",
        isActive
          ? "bg-gradient-to-r from-primary/15 to-primary/5 text-foreground font-medium shadow-depth"
          : "text-muted-foreground hover:bg-accent/60 hover:text-foreground hover:shadow-depth",
      )}
      aria-current={isActive ? "page" : undefined}
    >
      <span
        className={cn(
          "relative flex items-center justify-center transition-colors duration-150",
          isActive ? "text-primary" : "text-muted-foreground group-hover:text-muted-foreground/70",
        )}
        aria-hidden="true"
      >
        {item.icon}
        {item.countLoader && item.countLoader() > 0 && (
          <span
            className={cn(
              "absolute -right-1.5 -top-1.5 flex h-3.5 min-w-[14px] items-center justify-center rounded-full px-1 text-[9px] font-bold",
              isActive
                ? "bg-primary text-primary-foreground"
                : "bg-muted-foreground/30 text-muted-foreground",
            )}
          >
            {item.countLoader() > 99 ? "99+" : item.countLoader()}
          </span>
        )}
      </span>
      {item.label}
    </Link>
  );
}

function SidebarBrand() {
  return (
    <div className="relative">
      {/* Subtle gradient background */}
      <div
        className="pointer-events-none absolute inset-0 rounded-none"
        style={{
          background:
            "linear-gradient(135deg, hsl(263 70% 68% / 0.08) 0%, transparent 60%)",
        }}
        aria-hidden="true"
      />
      <div className="relative flex h-14 items-center gap-3 border-b border-border/60 px-4">
        <div
          className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-primary to-primary/60 text-[11px] font-bold tracking-tight text-primary-foreground shadow-depth glow-primary"
          aria-hidden="true"
        >
          <Zap size={14} strokeWidth={2.5} />
        </div>
        <div className="flex flex-col">
          <span className="text-sm font-semibold tracking-tight text-foreground">
            Informes Badie
          </span>
          <span className="text-[10px] text-muted-foreground/50">Mgmt UI</span>
        </div>
      </div>
    </div>
  );
}

function RootLayout() {
  const { data: activeRuns } = useActiveRuns();
  const { data: configs } = useConfigs();
  const activeCount = activeRuns?.items?.length ?? 0;
  const configCount = configs?.length ?? 0;

  return (
    <div className="flex min-h-screen bg-background">
      {/* Sidebar */}
      <aside
        className="flex w-56 flex-shrink-0 flex-col border-r border-border shadow-depth"
        style={{
          background:
            "linear-gradient(180deg, hsl(240 10% 5.5% / 1) 0%, hsl(240 10% 4% / 1) 100%)",
        }}
      >
        <SidebarBrand />

        {/* Nav */}
        <nav
          className="flex flex-1 flex-col gap-0.5 p-2 pt-4"
          aria-label="Navegación principal"
        >
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              item={
                item.to === "/configs"
                  ? { ...item, countLoader: () => configCount }
                  : item
              }
            />
          ))}
        </nav>

        {/* Active runs + footer */}
        <div className="border-t border-border/60 px-4 py-3">
          {activeCount > 0 && (
            <div className="mb-2 flex items-center gap-2 rounded-md bg-blue-500/10 px-2.5 py-1.5">
              <span className="flex h-2 w-2 animate-pulse rounded-full bg-blue-400" />
              <span className="text-[11px] text-blue-400">
                {activeCount} run{activeCount !== 1 ? "s" : ""} activo
                {activeCount !== 1 ? "s" : ""}
              </span>
            </div>
          )}
          <div className="text-[11px] text-muted-foreground/40">
            v2.0.0 — Excel Reporter
          </div>
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