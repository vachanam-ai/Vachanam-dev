import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  clearToken,
  fetchMe,
  getToken,
  loginWithGoogle,
  loginWithPassword,
  logoutSession,
  registerClinic,
  resetPassword,
  setToken
} from "../api/client";

const AuthContext = createContext(null);

/** Role → landing route. Single source of truth for role-based homes. */
export const roleHome = (role) =>
  ({
    receptionist: "/queue",
    org_admin: "/dashboard",
    doctor: "/my-schedule",
    super_admin: "/admin",
    support: "/support-admin"
  })[role] ?? "/queue";

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(Boolean(getToken()));
  const [selectedBranchId, setSelectedBranchId] = useState(null);

  useEffect(() => {
    if (!getToken()) return;
    fetchMe()
      .then(setUser)
      .catch(() => clearToken())
      .finally(() => setLoading(false));
  }, []);

  const finishLogin = useCallback(async (data) => {
    setToken(data.access_token);
    const me = await fetchMe();
    setUser(me);
    return me;
  }, []);

  const login = useCallback(
    async (idToken) => finishLogin(await loginWithGoogle(idToken)),
    [finishLogin]
  );
  const loginPassword = useCallback(
    async (email, password, captchaToken) =>
      finishLogin(await loginWithPassword(email, password, captchaToken)),
    [finishLogin]
  );
  const register = useCallback(
    async (payload, captchaToken) => finishLogin(await registerClinic(payload, captchaToken)),
    [finishLogin]
  );
  const completePasswordReset = useCallback(
    async (email, code, password) => finishLogin(await resetPassword(email, code, password)),
    [finishLogin]
  );

  const logout = useCallback(async () => {
    try { await logoutSession(); } catch { /* local logout must still finish */ }
    finally {
      clearToken();
      setUser(null);
      window.location.assign("/login");
    }
  }, []);

  useEffect(() => {
    const ids = user?.branch_ids ?? [];
    if (!ids.length) {
      setSelectedBranchId(null);
      return;
    }
    const key = `vachanam_branch_${user.user_id}`;
    const saved = localStorage.getItem(key);
    setSelectedBranchId(ids.includes(saved) ? saved : ids[0]);
  }, [user]);

  const selectBranch = useCallback((branchId) => {
    if (!user?.branch_ids?.includes(branchId)) return;
    localStorage.setItem(`vachanam_branch_${user.user_id}`, branchId);
    setSelectedBranchId(branchId);
  }, [user]);

  const value = useMemo(
    () => ({
      user,
      loading,
      login,
      loginPassword,
      register,
      completePasswordReset,
      logout,
      role: user?.role ?? null,
      branchId: selectedBranchId,
      branchIds: user?.branch_ids ?? [],
      selectBranch
    }),
    [user, loading, selectedBranchId, selectBranch, login, loginPassword, register, completePasswordReset, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
};
