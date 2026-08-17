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

/** JWT claims are already signed by our backend. Reading them locally lets the
 * app render immediately; protected API calls still perform server-side
 * signature, revocation, and account validation. */
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
    receptionist: "/queue",
    org_admin: "/dashboard",
    doctor: "/my-schedule",
    super_admin: "/admin",
    support: "/support-admin"
  })[role] ?? "/queue";

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => sessionFromToken(getToken()));
  const [loading] = useState(false);
  const [selectedBranchId, setSelectedBranchId] = useState(null);

  useEffect(() => {
    if (!getToken()) return;
    fetchMe()
      .then(setUser)
      .catch(() => {
        clearToken();
        setUser(null);
      });
  }, []);

  const finishLogin = useCallback((data) => {
    setToken(data.access_token);
    const me = sessionFromToken(data.access_token);
    if (!me) {
      clearToken();
      throw new Error("The server returned an invalid session");
    }
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
