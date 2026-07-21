import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { roleHome, useAuth } from "../hooks/useAuth.jsx";
import { fetchBranchSettings } from "../api/client.js";
import ThemeToggle from "./ThemeToggle.jsx";

const NAV = {
  receptionist: [
    { to: "/queue", label: "Queue" },
    { to: "/walk-in", label: "Walk-in" },
    { to: "/treatments", label: "Treatments" },
    { to: "/patients", label: "Patients" },
    { to: "/availability", label: "Doctor leave" },
    { to: "/tickets", label: "Support" }
  ],
  org_admin: [
    { to: "/dashboard", label: "Dashboard" },
    { to: "/queue", label: "Queue" },
    { to: "/walk-in", label: "Walk-in" },
    { to: "/treatments", label: "Treatments" },
    { to: "/patients", label: "Patients" },
    { to: "/availability", label: "Doctor leave" },
    { to: "/my-schedule", label: "Doctors" },
    { to: "/settings", label: "Settings" },
    { to: "/tickets", label: "Support" }
  ],
  doctor: [
    { to: "/my-schedule", label: "My Schedule" },
    { to: "/queue", label: "Queue" },
    { to: "/treatments", label: "Treatments" },
    { to: "/tickets", label: "Support" }
  ],
  super_admin: [
    { to: "/admin", label: "Operations" },
    { to: "/admin/monitoring", label: "Monitoring" },
    { to: "/support-admin", label: "Support" }
  ],
  support: [
    { to: "/support-admin", label: "Support inbox" }
  ]
};

const ROLE_LABEL = {
  receptionist: "Reception",
  org_admin: "Clinic Owner",
  doctor: "Doctor",
  super_admin: "Vachanam Ops",
  support: "Vachanam Support"
};


export default function Shell() {
  const { user, role, logout, branchId, branchIds, selectBranch } = useAuth();
  const links = NAV[role] ?? [];
  const [menuOpen, setMenuOpen] = useState(false);
  const [branchNames, setBranchNames] = useState({});
  const location = useLocation();

  // Close the mobile drawer on navigation so it never stays open over content.
  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (branchIds.length < 2) return;
    let cancelled = false;
    Promise.all(branchIds.map(async (id) => {
      try {
        const branch = await fetchBranchSettings(id);
        return [id, branch.name];
      } catch {
        return [id, `Branch ${id.slice(0, 6)}`];
      }
    })).then((entries) => { if (!cancelled) setBranchNames(Object.fromEntries(entries)); });
    return () => { cancelled = true; };
  }, [branchIds]);

  const branchChooser = branchIds.length > 1 && (
    <label className="flex items-center gap-2 font-ui text-xs text-slate">
      <span className="sr-only">Active branch</span>
      <select className="input max-w-44 py-1.5 text-sm" value={branchId ?? ""}
        onChange={(event) => selectBranch(event.target.value)} aria-label="Active branch">
        {branchIds.map((id) => <option key={id} value={id}>{branchNames[id] ?? `Branch ${id.slice(0, 6)}`}</option>)}
      </select>
    </label>
  );

  return (
    <div className="flex min-h-[100dvh] flex-col">
      <header className="sticky top-0 z-30 border-b border-hairline bg-cream/80 backdrop-blur-md">
        {/* Full-bleed bar (Vinay 2026-07-12: "no scrolling on navbar, spread
            left corner to right corner") — the header ignores the page's
            max-w-6xl; brand left, links center-left, user block pinned right. */}
        <div className="flex h-14 w-full items-center gap-3 px-4 sm:gap-5 sm:px-6">
          {/* Brand → role home (dashboard for owners) */}
          <Link
            to={roleHome(role)}
            className="shrink-0 font-brand text-xl leading-none text-teal"
            aria-label="Go to home"
          >
            Vachanam
          </Link>

          {/* Inline nav only where ALL links fit without scrolling (lg+);
              below that the hamburger drawer takes over. */}
          <nav className="hidden items-center gap-0.5 lg:flex xl:gap-1">
            {links.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                className={({ isActive }) =>
                  `whitespace-nowrap rounded-lg px-2.5 py-1.5 font-ui text-sm transition ${
                    isActive
                      ? "bg-teal text-white shadow-card"
                      : "text-ink-soft hover:bg-teal-mint"
                  }`
                }
              >
                {l.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex min-w-0 shrink-0 items-center gap-2.5">
            <div className="hidden sm:block">{branchChooser}</div>
            <ThemeToggle />
            <div className="hidden min-w-0 max-w-[180px] text-right lg:block">
              <p className="truncate font-ui text-sm font-medium leading-tight">{user?.name ?? user?.email}</p>
              <p className="truncate font-ui text-[10px] uppercase tracking-[0.14em] text-slate">
                {ROLE_LABEL[role] ?? role}
              </p>
            </div>
            <button
              onClick={logout}
              className="btn-ghost hidden shrink-0 whitespace-nowrap px-3 py-1.5 text-sm lg:inline-flex"
            >
              Sign out
            </button>

            {/* Mobile hamburger — only when there is something to navigate to */}
            {links.length > 0 && (
              <button
                type="button"
                aria-label={menuOpen ? "Close menu" : "Open menu"}
                aria-expanded={menuOpen}
                onClick={() => setMenuOpen((o) => !o)}
                className="grid h-11 w-11 place-items-center rounded-lg border border-hairline bg-surface text-ink-soft transition hover:bg-teal-mint lg:hidden"
              >
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                  strokeWidth="2" strokeLinecap="round" aria-hidden>
                  {menuOpen ? (
                    <>
                      <line x1="6" y1="6" x2="18" y2="18" />
                      <line x1="18" y1="6" x2="6" y2="18" />
                    </>
                  ) : (
                    <>
                      <line x1="3" y1="6" x2="21" y2="6" />
                      <line x1="3" y1="12" x2="21" y2="12" />
                      <line x1="3" y1="18" x2="21" y2="18" />
                    </>
                  )}
                </svg>
              </button>
            )}
          </div>
        </div>

        {/* Mobile drawer */}
        {menuOpen && (
          <nav className="border-t border-hairline bg-cream/95 px-4 py-3 backdrop-blur-md lg:hidden">
            <div className="mb-3 sm:hidden">{branchChooser}</div>
            <div className="mb-2 sm:hidden">
              <p className="font-ui text-sm font-medium leading-tight">{user?.name ?? user?.email}</p>
              <p className="font-ui text-[11px] uppercase tracking-[0.14em] text-slate">
                {ROLE_LABEL[role] ?? role}
              </p>
            </div>
            <div className="flex flex-col gap-1">
              {links.map((l) => (
                <NavLink
                  key={l.to}
                  to={l.to}
                  className={({ isActive }) =>
                    `flex min-h-[44px] items-center rounded-lg px-4 font-ui text-base transition ${
                      isActive
                        ? "bg-teal text-white shadow-card"
                        : "text-ink-soft hover:bg-teal-mint"
                    }`
                  }
                >
                  {l.label}
                </NavLink>
              ))}
              <button
                onClick={logout}
                className="mt-1 flex min-h-[44px] items-center rounded-lg border border-hairline px-4 font-ui text-base text-teal transition hover:bg-teal-mint"
              >
                Sign out
              </button>
            </div>
          </nav>
        )}
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        <Outlet />
      </main>

      <footer className="border-t border-hairline py-4 text-center font-ui text-xs text-slate">
        © 2026 Vachanam · healing starts with being heard
      </footer>
    </div>
  );
}
