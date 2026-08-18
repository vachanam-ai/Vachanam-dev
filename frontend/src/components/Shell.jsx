import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bell, CalendarDots, CalendarX, CaretDown, ChartLineUp, ChatCircleDots,
  CreditCard, FirstAidKit, GearSix, List, ListBullets, Plus, Pulse,
  SignOut, SquaresFour, Stethoscope, UserPlus, UsersThree, WhatsappLogo,
  Waveform,
} from "@phosphor-icons/react";
import { roleHome, useAuth } from "../hooks/useAuth.jsx";
import { fetchBranchSettings, fetchDoctors, fetchPlan, fetchStaff } from "../api/client.js";
import ThemeToggle from "./ThemeToggle.jsx";
import { WHATSAPP_SELF_SERVE_LIVE } from "../lib/plans.js";

const NAV = {
  receptionist: [
    ["/dashboard", "Overview", SquaresFour], ["/queue", "Live queue", ListBullets],
    ["/walk-in", "Add walk-in", UserPlus],
    ["/treatments", "Treatments", FirstAidKit], ["/patients", "Patients", UsersThree],
    ["/availability", "Doctor leave", CalendarX], ["/tickets", "Support", ChatCircleDots],
  ],
  org_admin: [
    ["/dashboard", "Overview", SquaresFour], ["/queue", "Live queue", ListBullets],
    ["/walk-in", "Add walk-in", UserPlus], ["/treatments", "Treatments", FirstAidKit],
    ["/patients", "Patients", UsersThree], ["/availability", "Doctor leave", CalendarX],
    ["/my-schedule", "Doctors", CalendarDots], ["/voices", "Voices", Waveform],
    ["/whatsapp", "WhatsApp", WhatsappLogo],
    ["/whatsapp/chats", "Conversations", ChatCircleDots], ["/billing", "Plan & billing", CreditCard],
    ["/settings", "Clinic settings", GearSix], ["/tickets", "Support", Bell],
  ],
  doctor: [
    ["/my-schedule", "My schedule", CalendarDots], ["/queue", "Live queue", ListBullets],
    ["/treatments", "Treatments", FirstAidKit], ["/tickets", "Support", ChatCircleDots],
  ],
  super_admin: [
    ["/admin", "Operations", Stethoscope], ["/admin/monitoring", "System health", Pulse],
    ["/support-admin", "Support inbox", ChatCircleDots],
  ],
  support: [["/support-admin", "Support inbox", ChatCircleDots]],
};

const ROLE_LABEL = {
  receptionist: "Reception", org_admin: "Clinic owner", doctor: "Doctor",
  super_admin: "Vachanam operations", support: "Vachanam support",
};

// The app is route-split, so warm the small page modules while the browser is
// idle. Navigation then starts the API request immediately instead of waiting
// for a second Cloudflare round trip before React can mount the page.
const ROUTE_PRELOADERS = {
  "/dashboard": () => import("../pages/Dashboard.jsx"),
  "/queue": () => import("../pages/Queue.jsx"),
  "/walk-in": () => import("../pages/WalkIn.jsx"),
  "/treatments": () => import("../pages/Treatments.jsx"),
  "/patients": () => import("../pages/Patients.jsx"),
  "/availability": () => import("../pages/Availability.jsx"),
  "/my-schedule": () => import("../pages/DoctorSchedule.jsx"),
  "/settings": () => import("../pages/Settings.jsx"),
  "/billing": () => import("../pages/Billing.jsx"),
  "/voices": () => import("../pages/Voices.jsx"),
  "/whatsapp": () => import("../pages/WhatsApp.jsx"),
  "/whatsapp/chats": () => import("../pages/WhatsAppChats.jsx"),
  "/tickets": () => import("../pages/MyTickets.jsx"),
  "/admin": () => import("../pages/Admin.jsx"),
  "/admin/monitoring": () => import("../pages/Monitoring.jsx"),
  "/support-admin": () => import("../pages/SupportAdmin.jsx"),
};

function preloadRoute(to) {
  return ROUTE_PRELOADERS[to]?.().catch(() => undefined);
}

const navFor = (role) => (NAV[role] ?? []).map(([to, label, Icon]) => ({ to, label, Icon }));

function initials(value) {
  const parts = (value ?? "").trim().split(/[\s@._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "V") + (parts[1]?.[0] ?? "")).toUpperCase();
}

function Avatar({ name, online = false, large = false }) {
  return (
    <span className={`app-avatar ${large ? "app-avatar-lg" : ""}`} aria-hidden>
      {initials(name)}
      {online && <span className="app-avatar-status" />}
    </span>
  );
}

function BrandMark({ compact = false }) {
  return (
    <span className="brand-lockup">
      <span className="brand-symbol" aria-hidden><img src="/vachanam-mark.png" alt="" /></span>
      {!compact && <span><strong>Vachanam</strong><small>Clinic intelligence</small></span>}
    </span>
  );
}

function SidebarContent({ role, links, user, logout, branchChooser, onNavigate, doctors, team, counts }) {
  return (
    <div className="app-sidebar-inner">
      <Link to={roleHome(role)} onClick={onNavigate} className="app-brand-link" aria-label="Vachanam home">
        <BrandMark />
      </Link>

      <div className="app-sidebar-scroll">
        <p className="app-nav-label">Workspace</p>
        <nav className="app-nav" aria-label="Primary navigation">
          {links.map(({ to, label, Icon }) => (
            <NavLink
              key={to}
              to={to}
              onClick={onNavigate}
              onPointerEnter={() => preloadRoute(to)}
              onFocus={() => preloadRoute(to)}
              className={({ isActive }) => `app-nav-item ${isActive ? "is-active" : ""}`}
            >
              <Icon size={20} weight="duotone" aria-hidden />
              <span>{label}</span>
              {!WHATSAPP_SELF_SERVE_LIVE && to === "/whatsapp" && <span className="app-nav-count">Soon</span>}
              {counts?.[to] > 0 && <span className="app-nav-count">{counts[to]}</span>}
            </NavLink>
          ))}
        </nav>

        {doctors?.length > 0 && (
          <section className="app-roster" aria-labelledby="doctors-nav-heading">
            <p id="doctors-nav-heading" className="app-nav-label">Care team</p>
            {doctors.slice(0, 5).map((doctor) => {
              const id = doctor.id ?? doctor.doctor_id;
              return (
                <Link key={id} to="/my-schedule" onClick={onNavigate} className="app-person-row">
                  <Avatar name={doctor.name} online />
                  <span className="app-person-copy"><strong>{doctor.name}</strong><small>Doctor</small></span>
                  {counts?.doctors?.[id] > 0 && <span className="app-nav-count">{counts.doctors[id]}</span>}
                </Link>
              );
            })}
            {team?.slice(0, 3).map((member) => (
              <div key={member.id ?? member.email} className="app-person-row">
                <Avatar name={member.name ?? member.email} />
                <span className="app-person-copy"><strong>{member.name ?? member.email}</strong><small>{(member.role ?? "team").replace("_", " ")}</small></span>
              </div>
            ))}
          </section>
        )}
      </div>

      <div className="app-sidebar-bottom">
        {branchChooser}
        <div className="app-account-card">
          <Avatar name={user?.name ?? user?.email} large />
          <span className="app-person-copy"><strong>{user?.name ?? user?.email}</strong><small>{ROLE_LABEL[role] ?? role}</small></span>
          <ThemeToggle />
          <button type="button" onClick={logout} className="icon-button icon-button-dark" aria-label="Sign out">
            <SignOut size={19} weight="bold" />
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Shell() {
  const { user, role, logout, branchId, branchIds = [], selectBranch } = useAuth();
  const queryClient = useQueryClient();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [branchNames, setBranchNames] = useState({});
  const [loadSidebarData, setLoadSidebarData] = useState(false);

  // Let the route's primary ledger request take the first available DB
  // connection. Sidebar metadata is useful, but it must not delay the page the
  // user actually opened on the deliberately small Supabase session pool.
  useEffect(() => {
    const start = () => setLoadSidebarData(true);
    if ("requestIdleCallback" in window) {
      const id = window.requestIdleCallback(start, { timeout: 500 });
      return () => window.cancelIdleCallback(id);
    }
    const id = window.setTimeout(start, 300);
    return () => window.clearTimeout(id);
  }, []);

  useEffect(() => {
    const warmRoutes = () => {
      navFor(role).forEach(({ to }) => { void preloadRoute(to); });
    };
    if ("requestIdleCallback" in window) {
      const id = window.requestIdleCallback(warmRoutes, { timeout: 2500 });
      return () => window.cancelIdleCallback(id);
    }
    const id = window.setTimeout(warmRoutes, 1500);
    return () => window.clearTimeout(id);
  }, [role]);

  const plan = useQuery({ queryKey: ["plan"], queryFn: fetchPlan, enabled: loadSidebarData && role === "org_admin", staleTime: 60_000 });
  const hasWhatsapp = WHATSAPP_SELF_SERVE_LIVE || Boolean(plan.data?.whatsapp_included || plan.data?.whatsapp_addon);
  const links = navFor(role).filter((item) => {
    if (item.to === "/whatsapp") return true;
    if (!WHATSAPP_SELF_SERVE_LIVE && item.to.startsWith("/whatsapp")) return false;
    return !item.to.startsWith("/whatsapp") || hasWhatsapp;
  });
  const hasBranch = ["org_admin", "receptionist", "doctor"].includes(role);
  const { data: doctorsRaw } = useQuery({
    queryKey: ["doctors", branchId], queryFn: () => fetchDoctors(branchId),
    enabled: Boolean(loadSidebarData && branchId && hasBranch), staleTime: 60_000,
  });
  const { data: team } = useQuery({
    queryKey: ["staff", branchId], queryFn: () => fetchStaff(branchId),
    enabled: Boolean(loadSidebarData && branchId && role === "org_admin"), staleTime: 60_000,
  });
  const doctors = Array.isArray(doctorsRaw) ? doctorsRaw : doctorsRaw?.doctors ?? [];
  const queue = queryClient.getQueryData(["queue", branchId]);
  const counts = { doctors: {} };
  if (queue?.doctors) {
    let waiting = 0;
    queue.doctors.forEach((doctor) => {
      const count = doctor.patients.filter((patient) => !["attended", "no_show"].includes(patient.status)).length;
      counts.doctors[doctor.doctor_id] = count;
      waiting += count;
    });
    if (waiting) counts["/queue"] = waiting;
  }

  const activeLink = links.find((item) => location.pathname === item.to || location.pathname.startsWith(item.to + "/"));
  const pageLabel = activeLink?.label ?? "Vachanam";
  const profileTo = role === "org_admin" ? "/settings" : roleHome(role);
  const topAction = WHATSAPP_SELF_SERVE_LIVE && location.pathname === "/whatsapp"
    ? { to: "/whatsapp?new=1", label: "New template" }
    : links.some((item) => item.to === "/walk-in") ? { to: "/walk-in", label: "Add walk-in" } : null;

  useEffect(() => { setMenuOpen(false); }, [location.pathname]);
  useEffect(() => {
    if (!menuOpen) return undefined;
    const onKey = (event) => { if (event.key === "Escape") setMenuOpen(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [menuOpen]);
  useEffect(() => {
    if (branchIds.length < 2) return undefined;
    let active = true;
    Promise.all(branchIds.map(async (id) => {
      try { return [id, (await fetchBranchSettings(id)).name]; }
      catch { return [id, "Branch " + id.slice(0, 6)]; }
    })).then((entries) => { if (active) setBranchNames(Object.fromEntries(entries)); });
    return () => { active = false; };
  }, [branchIds]);

  const branchChooser = branchIds.length > 1 ? (
    <label className="app-branch-select">
      <span>Active branch</span>
      <span className="app-select-wrap">
        <select value={branchId ?? ""} onChange={(event) => selectBranch(event.target.value)}>
          {branchIds.map((id) => <option key={id} value={id}>{branchNames[id] ?? "Branch " + id.slice(0, 6)}</option>)}
        </select>
        <CaretDown size={14} weight="bold" aria-hidden />
      </span>
    </label>
  ) : null;

  return (
    <div className="app-shell" data-app-shell>
      <aside className="app-sidebar">
        <SidebarContent {...{ role, links, user, logout, branchChooser, doctors, team, counts }} />
      </aside>

      <div className="app-main-column">
        <header className="app-topbar">
          <button type="button" className="icon-button app-menu-button" aria-label="Open menu" aria-expanded={menuOpen} onClick={() => setMenuOpen(true)}>
            <List size={22} weight="bold" />
          </button>
          <div className="app-mobile-brand"><BrandMark compact /></div>
          <div className="app-page-context"><span>Clinic workspace</span><strong>{pageLabel}</strong></div>
          <div className="app-topbar-actions">
            {topAction && <Link to={topAction.to} className="btn-primary" data-testid="top-action"><Plus size={18} weight="bold" />{topAction.label}</Link>}
            <Link to={profileTo} className="app-profile-pill"><Avatar name={user?.name ?? user?.email} /><span><strong>{user?.name ?? user?.email}</strong><small>{ROLE_LABEL[role] ?? role}</small></span></Link>
          </div>
        </header>

        <main className="app-content"><Outlet /></main>
        <footer className="app-footer"><span>Vachanam</span><span>Care begins with being heard.</span></footer>
      </div>

      <div className={`app-drawer ${menuOpen ? "is-open" : ""}`} aria-hidden={!menuOpen}>
        <button type="button" className="app-drawer-scrim" onClick={() => setMenuOpen(false)} aria-label="Close menu" />
        <aside className="app-drawer-panel" role="dialog" aria-modal="true" aria-label="Navigation menu">
          <SidebarContent {...{ role, links, user, logout, branchChooser, doctors, team, counts }} onNavigate={() => setMenuOpen(false)} />
        </aside>
      </div>
    </div>
  );
}
