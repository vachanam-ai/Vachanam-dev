import { Link } from "react-router-dom";
import { roleHome, useAuth } from "../hooks/useAuth.jsx";

/**
 * 404 — Vinay 2026-08-14.
 *
 * The catch-all route used to `<Navigate>` silently to the dashboard (or
 * /login). A mistyped or dead URL therefore looked like it had worked: the
 * user landed somewhere real, with no hint that the page they asked for does
 * not exist. Worse for a shared or bookmarked link — a receptionist following
 * a stale URL just ends up on the queue and assumes that WAS the link.
 *
 * Say what happened, then offer the way back. No auto-redirect: bouncing
 * people is what caused the confusion in the first place.
 */
export default function NotFound() {
  const { user, role } = useAuth();
  const home = user ? roleHome(role) : "/";

  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center px-6 text-center">
      <p className="font-ui text-sm font-semibold tracking-widest text-slate">404</p>
      <h1 className="mt-3 font-display text-3xl text-ink">This page doesn't exist</h1>
      <p className="mt-3 max-w-md font-ui text-sm text-slate">
        The link may be out of date, or the address may have a typo. Nothing has
        gone wrong with your clinic&apos;s account.
      </p>
      <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
        <Link className="btn-primary" to={home}>
          {user ? "Back to your dashboard" : "Back to home"}
        </Link>
        <Link className="btn-ghost" to="/help">
          Help centre
        </Link>
      </div>
    </div>
  );
}
