import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { roleHome, useAuth } from "../hooks/useAuth.jsx";
import { fetchBranchSettings } from "../api/client.js";
import ThemeToggle from "./ThemeToggle.jsx";

/* Stroke-icon set (inline SVG, no dependency). Keyed to the nav routes so the
   left sidebar reads like the BizLink reference at a glance. */
const I = {
  dashboard: "M3 3h7v7H3zM14 3h7v4h-7zM14 10h7v11h-7zM3 13h7v8H3z",
  queue: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  walkin: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M19 8v6M22 11h-6",
  treatments: "M9 2h6v4h4a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h4zM12 11v6M9 14h6",
  patients: "M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75",
  availability: "M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2M9 16l2 2 4-4",
  schedule: "M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2M12 14h.01M8 14h.01M16 14h.01M12 18h.01M8 18h.01",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z",
  support: "M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 0 1-3.46 0",
  admin: "M4 4h16v6H4zM4 14h16v6H4zM8 7h.01M8 17h.01",
  monitoring: "M22 12h-4l-3 9L9 3l-3 9H2"
};

const NAV = {
  receptionist: [
    { to: "/queue", label: "Queue", icon: "queue" },
    { to: "/walk-in", label: "Walk-in", icon: "walkin" },
    { to: "/treatments", label: "Treatments", icon: "treatments" },
    { to: "/patients", label: "Patients", icon: "patients" },
    { to: "/availability", label: "Doctor leave", icon: "availability" },
    { to: "/tickets", label: "Support", icon: "support" }
  ],
  org_admin: [
    { to: "/dashboard", label: "Dashboard", icon: "dashboard" },
    { to: "/queue", label: "Queue", icon: "queue" },
    { to: "/walk-in", label: "Walk-in", icon: "walkin" },
    { to: "/treatments", label: "Treatments", icon: "treatments" },
    { to: "/patients", label: "Patients", icon: "patients" },
    { to: "/availability", label: "Doctor leave", icon: "availability" },
    { to: "/my-schedule", label: "Doctors", icon: "schedule" },
    { to: "/settings", label: "Settings", icon: "settings" },
    { to: "/tickets", label: "Support", icon: "support" }
  ],
  doctor: [
    { to: "/my-schedule", label: "My Schedule", icon: "schedule" },
    { to: "/queue", label: "Queue", icon: "queue" },
    { to: "/treatments", label: "Treatments", icon: "treatments" },
    { to: "/tickets", label: "Support", icon: "support" }
  ],
  super_admin: [
    { to: "/admin", label: "Operations", icon: "admin" },
    { to: "/admin/monitoring", label: "Monitoring", icon: "monitoring" },
    { to: "/support-admin", label: "Support", icon: "support" }
  ],
  support: [{ to: "/support-admin", label: "Support inbox", icon: "support" }]
};

const ROLE_LABEL = {
  receptionist: "Reception",
  org_admin: "Clinic Owner",
  doctor: "Doctor",
  super_admin: "Vachanam Ops",
  support: "Vachanam Support"
};

function NavIcon({ name }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden className="shrink-0">
      <path d={I[name] ?? I.queue} />
    </svg>
  );
}

function initials(nameOrEmail) {
  const s = (nameOrEmail ?? "").trim();
  if (!s) return "··";
  const parts = s.split(/[\s@._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || s.slice(0, 2).toUpperCase();
}

/** Sidebar body — shared by the desktop rail and the mobile drawer. */
function SidebarContent({ role, links, user, logout, branchChooser, onNavigate }) {
  return (
    <div className="flex h-full flex-col">
      <Link to={roleHome(role)} onClick={onNavigate}
        className="mb-1 block px-3 py-1 font-brand text-lg font-semibold tracking-[-0.02em] text-ink">
        Vachanam
      </Link>

      <nav className="mt-2 flex flex-col gap-0.5">
        {links.map((l) => (
          <NavLink key={l.to} to={l.to} onClick={onNavigate}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-[10px] px-3 py-2 font-ui text-sm transition-colors ${
                isActive
                  ? "bg-pill font-semibold text-ink"
                  : "font-medium text-ink-soft hover:bg-pill"
              }`
            }>
            <NavIcon name={l.icon} />
            <span className="truncate">{l.label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="flex-1" />

      {branchChooser && <div className="mb-3 px-1">{branchChooser}</div>}

      <div className="mt-2 flex items-center gap-2.5 border-t border-hairline pt-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-line2 bg-pill text-[11px] font-semibold text-ink-soft">
          {initials(user?.name ?? user?.email)}
        </span>
        <div className="min-w-0 flex-1 leading-tight">
          <p className="truncate font-ui text-[13px] font-semibold text-ink">{user?.name ?? user?.email}</p>
          <p className="truncate font-ui text-[11px] text-slate">{ROLE_LABEL[role] ?? role}</p>
        </div>
        <ThemeToggle />
        <button onClick={logout} aria-label="Sign out"
          className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-slate transition-colors hover:bg-pill hover:text-ink">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
          </svg>
        </button>
      </div>
    </div>
  );
}

export default function Shell() {
  const { user, role, logout, branchId, branchIds, selectBranch } = useAuth();
  const links = NAV[role] ?? [];
  const [menuOpen, setMenuOpen] = useState(false);
  const [branchNames, setBranchNames] = useState({});
  const location = useLocation();

  useEffect(() => { setMenuOpen(false); }, [location.pathname]);

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
    <label className="block font-ui text-xs text-slate">
      <span className="sr-only">Active branch</span>
      <select className="field w-full py-2 text-sm" value={branchId ?? ""}
        onChange={(event) => selectBranch(event.target.value)} aria-label="Active branch">
        {branchIds.map((id) => <option key={id} value={id}>{branchNames[id] ?? `Branch ${id.slice(0, 6)}`}</option>)}
      </select>
    </label>
  );

  return (
    <div className="min-h-[100dvh] lg:grid lg:grid-cols-[248px_1fr]">
      {/* Desktop rail */}
      <aside className="sticky top-0 hidden h-[100dvh] flex-col border-r border-hairline bg-surface px-4 py-5 lg:flex">
        <SidebarContent role={role} links={links} user={user} logout={logout} branchChooser={branchChooser} />
      </aside>

      {/* Main column */}
      <div className="flex min-h-[100dvh] flex-col">
        {/* Mobile top bar */}
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-hairline bg-surface/85 px-4 backdrop-blur-md lg:hidden">
          {links.length > 0 && (
            <button type="button" aria-label="Open menu" aria-expanded={menuOpen}
              onClick={() => setMenuOpen(true)}
              className="grid h-10 w-10 place-items-center rounded-lg border border-hairline text-ink-soft transition hover:bg-pill">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                strokeWidth="2" strokeLinecap="round" aria-hidden>
                <line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" />
              </svg>
            </button>
          )}
          <Link to={roleHome(role)} className="font-brand text-lg font-semibold tracking-[-0.02em] text-ink">Vachanam</Link>
          <div className="ml-auto"><ThemeToggle /></div>
        </header>

        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6">
          <Outlet />
        </main>

        <footer className="border-t border-hairline py-4 text-center font-ui text-xs text-slate">
          © 2026 Vachanam · healing starts with being heard
        </footer>
      </div>

      {/* Mobile drawer */}
      <div className={`fixed inset-0 z-40 lg:hidden ${menuOpen ? "" : "pointer-events-none"}`} aria-hidden={!menuOpen}>
        <div onClick={() => setMenuOpen(false)}
          className={`absolute inset-0 bg-ink/40 backdrop-blur-sm transition-opacity duration-300 ${menuOpen ? "opacity-100" : "opacity-0"}`} />
        <aside className={`absolute left-0 top-0 h-full w-[80%] max-w-[300px] border-r border-hairline bg-surface px-4 py-5 shadow-lift transition-transform duration-300 ease-out ${menuOpen ? "translate-x-0" : "-translate-x-full"}`}>
          <SidebarContent role={role} links={links} user={user} logout={logout} branchChooser={branchChooser}
            onNavigate={() => setMenuOpen(false)} />
        </aside>
      </div>
    </div>
  );
}
