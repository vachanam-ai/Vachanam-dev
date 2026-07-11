import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { roleHome, useAuth } from "./hooks/useAuth.jsx";
import Shell from "./components/Shell.jsx";
import Landing from "./pages/Landing.jsx";
import Login from "./pages/Login.jsx";
import Register from "./pages/Register.jsx";
import Settings from "./pages/Settings.jsx";
import Queue from "./pages/Queue.jsx";
import WalkIn from "./pages/WalkIn.jsx";
import Treatments from "./pages/Treatments.jsx";
import Patients from "./pages/Patients.jsx";
import Availability from "./pages/Availability.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import DoctorSchedule from "./pages/DoctorSchedule.jsx";
import Admin from "./pages/Admin.jsx";
import Monitoring from "./pages/Monitoring.jsx";
import TvDisplay from "./pages/TvDisplay.jsx";
import Help from "./pages/Help.jsx";
import MyTickets from "./pages/MyTickets.jsx";
import SupportAdmin from "./pages/SupportAdmin.jsx";
import SupportWidget from "./components/SupportWidget.jsx";

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
            <Protected roles={["receptionist", "org_admin"]}>
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
            <Protected roles={["org_admin"]}>
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

      <Route path="*" element={<Navigate to={user ? roleHome(role) : "/login"} replace />} />
    </Routes>
    {showWidget && <SupportWidget />}
    </>
  );
}
