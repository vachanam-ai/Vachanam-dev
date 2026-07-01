import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../hooks/useAuth.jsx";

const NAV = {
  receptionist: [
    { to: "/queue", label: "Queue" },
    { to: "/walk-in", label: "Walk-in" },
    { to: "/treatments", label: "Treatments" },
    { to: "/patients", label: "Patients" },
    { to: "/availability", label: "Doctor leave" }
  ],
  org_admin: [
    { to: "/dashboard", label: "Dashboard" },
    { to: "/queue", label: "Queue" },
    { to: "/walk-in", label: "Walk-in" },
    { to: "/treatments", label: "Treatments" },
    { to: "/patients", label: "Patients" },
    { to: "/availability", label: "Doctor leave" },
    { to: "/my-schedule", label: "Doctors" },
    { to: "/settings", label: "Settings" }
  ],
  doctor: [
    { to: "/my-schedule", label: "My Schedule" },
    { to: "/treatments", label: "Treatments" }
  ],
  super_admin: [
    { to: "/admin", label: "Operations" },
    { to: "/admin/monitoring", label: "Monitoring" }
  ]
};

const ROLE_LABEL = {
  receptionist: "Reception",
  org_admin: "Clinic Owner",
  doctor: "Doctor",
  super_admin: "Vachanam Ops"
};

export default function Shell() {
  const { user, role, logout } = useAuth();
  const links = NAV[role] ?? [];
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();

  // Close the mobile drawer on navigation so it never stays open over content.
  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  return (
    <div className="flex min-h-[100dvh] flex-col">
      <header className="sticky top-0 z-30 border-b border-hairline bg-cream/80 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-4 sm:gap-6">
          <span className="font-brand text-xl leading-none text-teal">Vachanam</span>

          {/* Desktop / tablet inline nav */}
          <nav className="hidden items-center gap-1 md:flex">
            {links.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                className={({ isActive }) =>
                  `rounded-lg px-3 py-1.5 font-ui text-sm transition ${
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

          <div className="ml-auto flex items-center gap-3">
            <div className="hidden text-right sm:block">
              <p className="font-ui text-sm font-medium leading-tight">{user?.name ?? user?.email}</p>
              <p className="font-ui text-[11px] uppercase tracking-[0.14em] text-slate">
                {ROLE_LABEL[role] ?? role}
              </p>
            </div>
            <button onClick={logout} className="btn-ghost hidden px-3 py-1.5 text-sm md:inline-flex">
              Sign out
            </button>

            {/* Mobile hamburger — only when there is something to navigate to */}
            {links.length > 0 && (
              <button
                type="button"
                aria-label={menuOpen ? "Close menu" : "Open menu"}
                aria-expanded={menuOpen}
                onClick={() => setMenuOpen((o) => !o)}
                className="grid h-11 w-11 place-items-center rounded-lg border border-hairline bg-white text-ink-soft transition hover:bg-teal-mint md:hidden"
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
          <nav className="border-t border-hairline bg-cream/95 px-4 py-3 backdrop-blur-md md:hidden">
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
        Vachanam · healing starts with being heard
      </footer>
    </div>
  );
}
