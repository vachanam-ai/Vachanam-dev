import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { clearToken, fetchMe, getToken, loginWithGoogle, setToken } from "../api/client";

const AuthContext = createContext(null);

/** Role → landing route. Single source of truth for role-based homes. */
export const roleHome = (role) =>
  ({
    receptionist: "/queue",
    org_admin: "/dashboard",
    doctor: "/my-schedule",
    super_admin: "/admin"
  })[role] ?? "/queue";

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(Boolean(getToken()));

  useEffect(() => {
    if (!getToken()) return;
    fetchMe()
      .then(setUser)
      .catch(() => clearToken())
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (idToken) => {
    const data = await loginWithGoogle(idToken);
    setToken(data.access_token);
    const me = await fetchMe();
    setUser(me);
    return me;
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
    window.location.assign("/login");
  }, []);

  const value = useMemo(
    () => ({
      user,
      loading,
      login,
      logout,
      role: user?.role ?? null,
      branchId: user?.branch_ids?.[0] ?? null,
      branchIds: user?.branch_ids ?? []
    }),
    [user, loading, login, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
};
