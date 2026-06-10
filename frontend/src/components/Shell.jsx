import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../hooks/useAuth.jsx";

const NAV = {
  receptionist: [
    { to: "/queue", label: "Queue" },
    { to: "/walk-in", label: "Walk-in" }
  ],
  org_admin: [
    { to: "/dashboard", label: "Dashboard" },
    { to: "/queue", label: "Queue" },
    { to: "/walk-in", label: "Walk-in" }
  ],
  doctor: [{ to: "/my-schedule", label: "My Schedule" }],
  super_admin: [{ to: "/admin", label: "Operations" }]
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

  return (
    <div className="min-h-dvh flex flex-col">
      <header className="sticky top-0 z-30 border-b border-hairline bg-cream/80 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4">
          <span className="font-brand text-xl leading-none text-teal">Vachanam</span>

          <nav className="flex items-center gap-1">
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
            <button onClick={logout} className="btn-ghost px-3 py-1.5 text-sm">
              Sign out
            </button>
          </div>
        </div>
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
