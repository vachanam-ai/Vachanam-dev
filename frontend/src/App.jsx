import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { roleHome, useAuth } from "./hooks/useAuth.jsx";
import NotFound from "./pages/NotFound.jsx";

// Everything behind login (plus kiosk/help) loads on demand: a public visitor
// on the landing page should not download the dashboard, charts, or admin
// consoles (PSI: landing shipped the whole 550KB bundle, FIXLOG #338).
const Shell = lazy(() => import("./components/Shell.jsx"));
// Keep the marketing page out of authenticated reloads. It owns the large
// hero/motion bundle and is never rendered once a signed JWT is available.
const Landing = lazy(() => import("./pages/Landing.jsx"));
const Login = lazy(() => import("./pages/Login.jsx"));
const Register = lazy(() => import("./pages/Register.jsx"));
const Settings = lazy(() => import("./pages/Settings.jsx"));
const Billing = lazy(() => import("./pages/Billing.jsx"));
const Queue = lazy(() => import("./pages/Queue.jsx"));
const WalkIn = lazy(() => import("./pages/WalkIn.jsx"));
const Treatments = lazy(() => import("./pages/Treatments.jsx"));
const Patients = lazy(() => import("./pages/Patients.jsx"));
const Availability = lazy(() => import("./pages/Availability.jsx"));
const Dashboard = lazy(() => import("./pages/Dashboard.jsx"));
const DoctorSchedule = lazy(() => import("./pages/DoctorSchedule.jsx"));
const WhatsApp = lazy(() => import("./pages/WhatsApp.jsx"));
const WhatsAppChats = lazy(() => import("./pages/WhatsAppChats.jsx"));
const Voices = lazy(() => import("./pages/Voices.jsx"));
const Admin = lazy(() => import("./pages/Admin.jsx"));
const Monitoring = lazy(() => import("./pages/Monitoring.jsx"));
const TvDisplay = lazy(() => import("./pages/TvDisplay.jsx"));
const Help = lazy(() => import("./pages/Help.jsx"));
const MyTickets = lazy(() => import("./pages/MyTickets.jsx"));
const SupportAdmin = lazy(() => import("./pages/SupportAdmin.jsx"));
const SupportWidget = lazy(() => import("./components/SupportWidget.jsx"));

function FullScreenSpinner() {
  return (
    <div className="min-h-dvh grid place-items-center">
      <div className="flex flex-col items-center gap-3">
        <span className="font-brand text-3xl text-teal">Vachanam</span>
        <div className="h-1 w-24 overflow-hidden rounded-full bg-teal-pale">
          <div className="h-full w-1/2 animate-pulse rounded-full bg-teal" />
        </div>
      </div>
    </div>
  );
}

/** Route guard: requires login; optionally restricts to specific roles. */
function Protected({ roles, children }) {
  const { user, loading, role } = useAuth();
  const location = useLocation();
  if (loading) return <FullScreenSpinner />;
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />;
  if (roles && !roles.includes(role)) return <Navigate to={roleHome(role)} replace />;
  return children;
}

export default function App() {
  const { user, role } = useAuth();
  // Floating assistant is a CUSTOMER tool — show it to clinics + public
  // visitors, not to Vachanam's own support/ops staff (they use the dashboard).
  const showWidget = !["support", "super_admin"].includes(role);
  return (
    <>
    <Suspense fallback={<FullScreenSpinner />}>
    <Routes>
      <Route path="/" element={user ? <Navigate to={roleHome(role)} replace /> : <Landing />} />
      <Route path="/login" element={user ? <Navigate to={roleHome(role)} replace /> : <Login />} />
      <Route path="/register" element={user ? <Navigate to={roleHome(role)} replace /> : <Register />} />
      {/* Public waiting-room TV board — no login, no PII (token numbers only) */}
      <Route path="/tv/:branchId" element={<TvDisplay />} />
      {/* Public help centre — KB search + AI assistant (works logged out or in) */}
      <Route path="/help" element={<Help />} />

      <Route
        element={
          <Protected>
            <Shell />
          </Protected>
        }
      >
        <Route
          path="/queue"
          element={
            <Protected roles={["receptionist", "org_admin", "doctor"]}>
              <Queue />
            </Protected>
          }
        />
        <Route
          path="/walk-in"
          element={
            <Protected roles={["receptionist", "org_admin"]}>
              <WalkIn />
            </Protected>
          }
        />
        <Route
          path="/treatments"
          element={
            <Protected roles={["org_admin", "doctor", "receptionist"]}>
              <Treatments />
            </Protected>
          }
        />
        <Route
          path="/patients"
          element={
            <Protected roles={["org_admin", "receptionist"]}>
              <Patients />
            </Protected>
          }
        />
        <Route
          path="/availability"
          element={
            <Protected roles={["receptionist", "org_admin"]}>
              <Availability />
            </Protected>
          }
        />
        <Route
          path="/dashboard"
          element={
            <Protected roles={["org_admin", "receptionist"]}>
              <Dashboard />
            </Protected>
          }
        />
        <Route
          path="/my-schedule"
          element={
            <Protected roles={["doctor", "org_admin"]}>
              <DoctorSchedule />
            </Protected>
          }
        />
        <Route
          path="/settings"
          element={
            <Protected roles={["org_admin"]}>
              <Settings />
            </Protected>
          }
        />
        <Route
          path="/billing"
          element={
            <Protected roles={["org_admin"]}>
              <Billing />
            </Protected>
          }
        />
        <Route
          path="/voices"
          element={
            <Protected roles={["org_admin"]}>
              <Voices />
            </Protected>
          }
        />
        <Route
          path="/whatsapp"
          element={
            <Protected roles={["org_admin"]}>
              <WhatsApp />
            </Protected>
          }
        />
        <Route
          path="/whatsapp/chats"
          element={
            <Protected roles={["org_admin"]}>
              <WhatsAppChats />
            </Protected>
          }
        />
        <Route
          path="/tickets"
          element={
            <Protected roles={["org_admin", "receptionist", "doctor"]}>
              <MyTickets />
            </Protected>
          }
        />
        <Route
          path="/admin"
          element={
            <Protected roles={["super_admin"]}>
              <Admin />
            </Protected>
          }
        />
        <Route
          path="/admin/monitoring"
          element={
            <Protected roles={["super_admin"]}>
              <Monitoring />
            </Protected>
          }
        />
        <Route
          path="/support-admin"
          element={
            <Protected roles={["super_admin", "support"]}>
              <SupportAdmin />
            </Protected>
          }
        />
      </Route>

      {/* 404, not a silent redirect (Vinay 2026-08-14). Bouncing an unknown
          URL to the dashboard made a dead link look like it had worked. */}
      <Route path="*" element={<NotFound />} />
    </Routes>
    </Suspense>
    <Suspense fallback={null}>{showWidget && <SupportWidget />}</Suspense>
    </>
  );
}
