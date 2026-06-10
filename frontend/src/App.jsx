import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { roleHome, useAuth } from "./hooks/useAuth.jsx";
import Shell from "./components/Shell.jsx";
import Login from "./pages/Login.jsx";
import Queue from "./pages/Queue.jsx";
import WalkIn from "./pages/WalkIn.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import DoctorSchedule from "./pages/DoctorSchedule.jsx";
import Admin from "./pages/Admin.jsx";

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
  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to={roleHome(role)} replace /> : <Login />} />

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
            <Protected roles={["doctor"]}>
              <DoctorSchedule />
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
      </Route>

      <Route path="*" element={<Navigate to={user ? roleHome(role) : "/login"} replace />} />
    </Routes>
  );
}
