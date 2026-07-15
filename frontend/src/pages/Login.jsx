import ThemeToggle from "../components/ThemeToggle.jsx";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { roleHome, useAuth } from "../hooks/useAuth.jsx";
import { revealStagger } from "../lib/motion.js";
import { gsiTheme, watchTheme } from "../lib/gsiTheme.js";
import { forgotPassword, resetPassword } from "../api/client.js";
import Turnstile, { TURNSTILE_ON } from "../components/Turnstile.jsx";
import PasswordField from "../components/PasswordField.jsx";

// Escalating resend cooldowns: wait 30s before the first resend, 1min before
// the next, 5min after that (then holds). Backend email send-cooldown (25s)
// sits just below the first tier so a legit resend always goes through.
const RESEND_STEPS = [30, 60, 300];
const fmt = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;

export default function Login() {
  const { login, loginPassword } = useAuth();
  const navigate = useNavigate();
  const gsiRef = useRef(null);
  const pageRef = useRef(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [forgotOpen, setForgotOpen] = useState(false);
  const [fpStage, setFpStage] = useState("request"); // request | reset
  const [fpCode, setFpCode] = useState("");
  const [fpNew, setFpNew] = useState("");
  const [fpBusy, setFpBusy] = useState(false);
  const [ts, setTs] = useState(""); // current Turnstile token ("" = not solved yet)
  const [resendStep, setResendStep] = useState(0); // index into RESEND_STEPS
  const [resendLeft, setResendLeft] = useState(0); // seconds until resend allowed

  useEffect(() => {
    revealStagger(pageRef.current);
  }, []);

  // Countdown tick for the resend cooldown.
  useEffect(() => {
    if (resendLeft <= 0) return undefined;
    const id = setInterval(() => setResendLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(id);
  }, [resendLeft]);

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
      paint();
    };
    const paint = () => {
      if (cancelled || !gsiRef.current || !window.google?.accounts?.id) return;
      window.google.accounts.id.renderButton(gsiRef.current, {
        theme: gsiTheme(), // dark app → Google's filled_black (was a white slab)
        size: "large",
        shape: "pill",
        // Cap to the narrowest common phone content width (360px viewport minus
        // padding) so the rendered iframe never forces horizontal scroll.
        width: Math.min(320, gsiRef.current.offsetWidth || 320),
        text: "continue_with"
      });
    };
    mount();
    const stopWatch = watchTheme(paint); // re-render when the theme toggles
    return () => {
      cancelled = true;
      stopWatch();
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

  const requestReset = async (e) => {
    e.preventDefault();
    if (!email.trim()) return toast.error("Enter your email first");
    setFpBusy(true);
    try {
      const r = await forgotPassword(email.trim());
      // Dev (no email provider): the code is echoed so the flow is testable.
      if (r?.dev_email_code) toast.info(`Reset code: ${r.dev_email_code}`);
      setFpStage("reset");
      setResendStep(0);
      setResendLeft(RESEND_STEPS[0]); // 30s before the first resend
      toast.success("If that account exists, we emailed a reset code");
    } catch {
      toast.error("Could not send the reset code — try again");
    } finally {
      setFpBusy(false);
    }
  };

  const resendCode = async () => {
    if (resendLeft > 0 || fpBusy) return;
    setFpBusy(true);
    try {
      await forgotPassword(email.trim());
      const next = Math.min(resendStep + 1, RESEND_STEPS.length - 1);
      setResendStep(next);
      setResendLeft(RESEND_STEPS[next]); // 30s → 1min → 5min
      toast.success("New code sent — check your email");
    } catch {
      toast.error("Could not resend — try again");
    } finally {
      setFpBusy(false);
    }
  };

  const doReset = async (e) => {
    e.preventDefault();
    setFpBusy(true);
    try {
      await resetPassword(email.trim(), fpCode.trim(), fpNew);
    } catch (err) {
      // Distinct messages so a real failure is never mislabeled as "wrong code".
      const st = err?.response?.status;
      const detail = err?.response?.data?.detail;
      if (st === 401) toast.error("That code is wrong or expired — tap Resend for a fresh one");
      else if (st === 422) toast.error(detail ?? "Password doesn't meet the rules");
      else if (st === 429) toast.error("Too many attempts — wait a minute, then try again");
      else toast.error(detail ?? "Reset failed — try again");
      setFpBusy(false);
      return;
    }
    // Password is set. Sign in; if that hiccups, send them to the sign-in form.
    try {
      const me = await loginPassword(email.trim(), fpNew);
      toast.success("Password updated");
      navigate(roleHome(me.role), { replace: true });
    } catch {
      toast.success("Password updated — please sign in");
      setForgotOpen(false);
      setFpStage("request");
    } finally {
      setFpBusy(false);
    }
  };

  return (
    <div ref={pageRef} className="min-h-dvh grid lg:grid-cols-[1.1fr_1fr]">
      <ThemeToggle float />
      <section className="relative hidden overflow-hidden bg-[#0e4a49] text-white lg:flex lg:flex-col lg:justify-between lg:p-12">
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
          <p data-reveal className="mt-6 max-w-md font-ui text-[#cfe8e5]/90">
            Every call answered. Every token accounted for. Your front desk, your doctors,
            and your day — on one calm ledger.
          </p>
        </div>
        <p data-reveal className="relative font-ui text-xs text-[#cfe8e5]/60">
          vachanam.in · India
        </p>
      </section>

      <section className="grid place-items-center p-6 sm:p-8">
        <div className="w-full max-w-sm">
          <Link to="/" data-reveal className="mb-8 block lg:hidden">
            <span className="font-brand text-3xl text-teal">Vachanam</span>
          </Link>

          <p data-reveal className="eyebrow">Sign in</p>
          <h2 data-reveal className="mt-2 font-display text-3xl font-semibold tracking-tight">
            Open today&rsquo;s clinic
          </h2>

          {!forgotOpen ? (
            <form data-reveal onSubmit={submit} className="mt-8 space-y-4">
              <div>
                <label className="label">Email</label>
                <input className="field" type="email" value={email} required
                  onChange={(e) => setEmail(e.target.value)} placeholder="you@clinic.in" />
              </div>
              <div>
                <div className="flex items-center justify-between">
                  <label className="label">Password</label>
                  <button type="button"
                    onClick={() => { setForgotOpen(true); setFpStage("request"); }}
                    className="font-ui text-xs text-teal underline-offset-4 hover:underline">
                    Forgot password?
                  </button>
                </div>
                <PasswordField value={password} required autoComplete="current-password"
                  onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
              </div>
              <Turnstile onToken={setTs} />
              <button className="btn-primary w-full py-3"
                disabled={busy || (TURNSTILE_ON && !ts)}>
                {busy ? "Signing in…" : "Sign in"}
              </button>
            </form>
          ) : (
            <form data-reveal onSubmit={fpStage === "request" ? requestReset : doReset}
              className="mt-8 space-y-4">
              <div>
                <label className="label">Email</label>
                <input className="field" type="email" value={email} required
                  onChange={(e) => setEmail(e.target.value)} placeholder="you@clinic.in"
                  disabled={fpStage === "reset"} />
              </div>
              {fpStage === "reset" && (
                <>
                  <div>
                    <label className="label">Reset code</label>
                    <input className="field" inputMode="numeric" value={fpCode} required
                      onChange={(e) => setFpCode(e.target.value)} placeholder="6-digit code" />
                    <div className="mt-1.5 flex items-center justify-between">
                      <span className="font-ui text-xs text-slate">Didn&rsquo;t get it? Check spam.</span>
                      <button type="button" onClick={resendCode} disabled={resendLeft > 0 || fpBusy}
                        className="font-ui text-xs text-teal underline-offset-4 hover:underline disabled:text-slate disabled:no-underline">
                        {resendLeft > 0 ? `Resend in ${fmt(resendLeft)}` : "Resend code"}
                      </button>
                    </div>
                  </div>
                  <div>
                    <label className="label">New password</label>
                    <PasswordField value={fpNew} required autoComplete="new-password"
                      onChange={(e) => setFpNew(e.target.value)} placeholder="••••••••" />
                  </div>
                </>
              )}
              {fpStage === "request" && <Turnstile onToken={setTs} />}
              <button className="btn-primary w-full py-3"
                disabled={fpBusy || (fpStage === "request" && TURNSTILE_ON && !ts)}>
                {fpBusy
                  ? "Working…"
                  : fpStage === "request" ? "Email me a reset code" : "Set new password & sign in"}
              </button>
              <button type="button" onClick={() => setForgotOpen(false)}
                className="w-full font-ui text-sm text-slate underline-offset-4 hover:underline">
                Back to sign in
              </button>
            </form>
          )}

          <div data-reveal className="my-6 flex items-center gap-3">
            <span className="h-px flex-1 bg-hairline" />
            <span className="font-ui text-xs uppercase tracking-[0.14em] text-slate">or</span>
            <span className="h-px flex-1 bg-hairline" />
          </div>

          <div data-reveal>
            {GOOGLE_CLIENT_ID ? (
              <div className="flex justify-center">
                <div ref={gsiRef} className="gsi-crop" />
              </div>
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
