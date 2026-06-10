import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { roleHome, useAuth } from "../hooks/useAuth.jsx";
import { revealStagger } from "../lib/motion.js";

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;

export default function Login() {
  const { login, loginPassword } = useAuth();
  const navigate = useNavigate();
  const gsiRef = useRef(null);
  const pageRef = useRef(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    revealStagger(pageRef.current);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const mount = () => {
      if (cancelled) return;
      if (!window.google?.accounts?.id) return void setTimeout(mount, 150);
      if (!GOOGLE_CLIENT_ID) return;
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: async (resp) => {
          try {
            const me = await login(resp.credential);
            navigate(roleHome(me.role), { replace: true });
          } catch (e) {
            const detail = e?.response?.data?.detail ?? "";
            if (e?.response?.status === 403) {
              toast.info("No account yet — register your clinic first");
              navigate("/register");
            } else {
              toast.error(detail || "Sign-in failed");
            }
          }
        }
      });
      window.google.accounts.id.renderButton(gsiRef.current, {
        theme: "outline",
        size: "large",
        shape: "pill",
        width: 320,
        text: "continue_with"
      });
    };
    mount();
    return () => {
      cancelled = true;
    };
  }, [login, navigate]);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const me = await loginPassword(email.trim(), password);
      navigate(roleHome(me.role), { replace: true });
    } catch (err) {
      toast.error(err?.response?.data?.detail ?? "Invalid email or password");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div ref={pageRef} className="min-h-dvh grid lg:grid-cols-[1.1fr_1fr]">
      <section className="relative hidden overflow-hidden bg-teal-deep text-white lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.12]"
          style={{
            backgroundImage:
              "radial-gradient(700px 420px at 80% 10%, #80CBC4, transparent 60%), radial-gradient(500px 380px at 10% 90%, #008F8F, transparent 55%)"
          }}
        />
        <Link to="/" data-reveal className="font-brand text-3xl">Vachanam</Link>
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

      <section className="grid place-items-center p-8">
        <div className="w-full max-w-sm">
          <Link to="/" data-reveal className="mb-8 block lg:hidden">
            <span className="font-brand text-3xl text-teal">Vachanam</span>
          </Link>

          <p data-reveal className="eyebrow">Sign in</p>
          <h2 data-reveal className="mt-2 font-display text-3xl font-semibold tracking-tight">
            Open today&rsquo;s clinic
          </h2>

          <form data-reveal onSubmit={submit} className="mt-8 space-y-4">
            <div>
              <label className="label">Email</label>
              <input className="field" type="email" value={email} required
                onChange={(e) => setEmail(e.target.value)} placeholder="you@clinic.in" />
            </div>
            <div>
              <label className="label">Password</label>
              <input className="field" type="password" value={password} required
                onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
            </div>
            <button className="btn-primary w-full py-3" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>

          <div data-reveal className="my-6 flex items-center gap-3">
            <span className="h-px flex-1 bg-hairline" />
            <span className="font-ui text-xs uppercase tracking-[0.14em] text-slate">or</span>
            <span className="h-px flex-1 bg-hairline" />
          </div>

          <div data-reveal>
            {GOOGLE_CLIENT_ID ? (
              <div ref={gsiRef} className="flex justify-center" />
            ) : (
              <div className="card p-4 font-ui text-sm text-danger">
                VITE_GOOGLE_CLIENT_ID missing — add it to frontend/.env.local
              </div>
            )}
          </div>

          <p data-reveal className="mt-8 text-center font-ui text-sm text-slate">
            New clinic?{" "}
            <Link to="/register" className="font-medium text-teal underline-offset-4 hover:underline">
              Start your 14-day free trial
            </Link>
          </p>
        </div>
      </section>
    </div>
  );
}
