import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  clearToken,
  fetchMe,
  loginWithGoogle,
  loginWithPassword,
  logoutSession,
  registerClinic,
  resetPassword
} from "../api/client";

const AuthContext = createContext(null);

/** Legacy decoder retained only for old unit/API consumers. Browser sessions
 * never call it: their JWT stays inside the HttpOnly cookie. */
export const sessionFromToken = (token) => {
  try {
    const encoded = token?.split(".")[1];
    if (!encoded) return null;
    const padded = encoded.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(encoded.length / 4) * 4, "=");
    const claims = JSON.parse(atob(padded));
    if (!claims.sub || !claims.email || !claims.role || Number(claims.exp) * 1000 <= Date.now()) return null;
    return {
      user_id: claims.sub,
      email: claims.email,
      role: claims.role,
      org_id: claims.org_id ?? null,
      branch_ids: claims.branch_ids ?? [],
      is_admin: Boolean(claims.is_admin)
    };
  } catch {
    return null;
  }
};

/** Role → landing route. Single source of truth for role-based homes. */
export const roleHome = (role) =>
  ({
    receptionist: "/dashboard",
    org_admin: "/dashboard",
    doctor: "/my-schedule",
    super_admin: "/admin",
    support: "/support-admin"
  })[role] ?? "/queue";

const initialBranch = (user) => {
  const ids = user?.branch_ids ?? [];
  if (!ids.length) return null;
  const saved = localStorage.getItem(`vachanam_branch_${user.user_id}`);
  return ids.includes(saved) ? saved : ids[0];
};

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedBranchId, setSelectedBranchId] = useState(null);

  useEffect(() => {
    clearToken();
    fetchMe()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const finishLogin = useCallback(async () => {
    const me = await fetchMe();
    setUser(me);
    setSelectedBranchId(initialBranch(me));
    return me;
  }, []);

  const login = useCallback(
    async (idToken) => { await loginWithGoogle(idToken); return finishLogin(); },
    [finishLogin]
  );
  const loginPassword = useCallback(
    async (email, password, captchaToken) =>
      { await loginWithPassword(email, password, captchaToken); return finishLogin(); },
    [finishLogin]
  );
  const register = useCallback(
    async (payload, captchaToken) => { await registerClinic(payload, captchaToken); return finishLogin(); },
    [finishLogin]
  );
  const completePasswordReset = useCallback(
    async (email, code, password) => { await resetPassword(email, code, password); return finishLogin(); },
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
