import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { roleHome, useAuth } from "../hooks/useAuth.jsx";
import { revealStagger } from "../lib/motion.js";

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const gsiRef = useRef(null);
  const pageRef = useRef(null);

  useEffect(() => {
    revealStagger(pageRef.current);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const mount = () => {
      if (cancelled) return;
      if (!window.google?.accounts?.id) {
        setTimeout(mount, 150);
        return;
      }
      if (!GOOGLE_CLIENT_ID) return;
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: async (resp) => {
          try {
            const me = await login(resp.credential);
            navigate(roleHome(me.role), { replace: true });
          } catch (e) {
            toast.error(
              e?.response?.data?.detail ?? "Sign-in failed — is your account registered for a clinic?"
            );
          }
        }
      });
      window.google.accounts.id.renderButton(gsiRef.current, {
        theme: "outline",
        size: "large",
        shape: "pill",
        width: 280,
        text: "continue_with"
      });
    };
    mount();
    return () => {
      cancelled = true;
    };
  }, [login, navigate]);

  return (
    <div ref={pageRef} className="min-h-dvh grid lg:grid-cols-[1.1fr_1fr]">
      {/* Editorial brand panel */}
      <section className="relative hidden overflow-hidden bg-teal-deep text-white lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.12]"
          style={{
            backgroundImage:
              "radial-gradient(700px 420px at 80% 10%, #80CBC4, transparent 60%), radial-gradient(500px 380px at 10% 90%, #008F8F, transparent 55%)"
          }}
        />
        <span data-reveal className="font-brand text-3xl">Vachanam</span>

        <div className="relative">
          <p data-reveal className="eyebrow !text-gold">Clinic console</p>
          <h1 data-reveal className="mt-3 font-display text-5xl font-semibold leading-[1.08] tracking-tight">
            Healing starts
            <br />
            with being <em className="font-normal italic text-gold">heard.</em>
          </h1>
          <p data-reveal className="mt-6 max-w-md font-ui text-teal-pale/90">
            Every call answered. Every token accounted for. Your front desk, your doctors,
            and your day — on one calm ledger.
          </p>
        </div>

        <p data-reveal className="relative font-ui text-xs text-teal-pale/60">
          vachanam.in · Hyderabad, India
        </p>
      </section>

      {/* Sign-in panel */}
      <section className="grid place-items-center p-8">
        <div className="w-full max-w-sm">
          <div data-reveal className="mb-8 lg:hidden">
            <span className="font-brand text-3xl text-teal">Vachanam</span>
          </div>

          <p data-reveal className="eyebrow">Sign in</p>
          <h2 data-reveal className="mt-2 font-display text-3xl font-semibold tracking-tight">
            Open today&rsquo;s clinic
          </h2>
          <p data-reveal className="mt-2 font-ui text-sm text-slate">
            Use the Google account your clinic registered with Vachanam.
          </p>

          <div data-reveal className="mt-8">
            {GOOGLE_CLIENT_ID ? (
              <div ref={gsiRef} className="flex justify-start" />
            ) : (
              <div className="card p-4 font-ui text-sm text-danger">
                VITE_GOOGLE_CLIENT_ID missing — add it to frontend/.env.local
              </div>
            )}
          </div>

          <p data-reveal className="mt-10 font-ui text-xs leading-relaxed text-slate">
            Access is role-based: reception sees the queue, owners see analytics, doctors see
            their schedule. Patient data stays inside your clinic — that&rsquo;s the deal, legally
            and otherwise.
          </p>
        </div>
      </section>
    </div>
  );
}
