import ThemeToggle from "../components/ThemeToggle.jsx";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { API_BASE, requestOtp } from "../api/client.js";
import Turnstile, { TURNSTILE_ON } from "../components/Turnstile.jsx";
import { roleHome, useAuth } from "../hooks/useAuth.jsx";
import { revealStagger } from "../lib/motion.js";
import { gsiTheme, watchTheme } from "../lib/gsiTheme.js";
import PasswordField from "../components/PasswordField.jsx";

const PLANS = { lite: "Lite", solo: "Starter", clinic: "Clinic", multi: "Multi" };
const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;

// Mirror backend validators so the user gets instant, identical feedback.
const emailError = (v) => {
  if (!v) return "Email is required";
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v) || v.includes("..")) return "Enter a valid email";
  return null;
};

// Live password checklist — mirrors validate_password() in the backend
// (Vinay 2026-06-15): 8+ chars, lowercase, uppercase, number, special char.
const passwordChecks = (v) => [
  { label: "8 characters", ok: v.length >= 8 },
  { label: "At least 1 number", ok: /\d/.test(v) },
  { label: "At least 1 lowercase and uppercase", ok: /[a-z]/.test(v) && /[A-Z]/.test(v) },
  { label: "At least 1 special character", ok: /[^A-Za-z0-9]/.test(v) }
];
const passwordError = (v) => (passwordChecks(v).every((c) => c.ok) ? null : "Password doesn't meet the rules below");

export default function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const pageRef = useRef(null);
  const [params] = useSearchParams();
  const planParam = params.get("plan");

  const [form, setForm] = useState({
    clinic_name: "",
    owner_name: "",
    email: "",
    password: "",
    plan: PLANS[planParam] ? planParam : "clinic"
  });
  const [touched, setTouched] = useState({});
  const [step, setStep] = useState("details"); // details | otp
  const [otp, setOtp] = useState("");
  const [devCode, setDevCode] = useState(null);
  const [busy, setBusy] = useState(false);
  const [ts, setTs] = useState(""); // current Turnstile token ("" = not solved yet)
  const tsRef = useRef("");
  useEffect(() => { tsRef.current = ts; }, [ts]);
  // DPDP: clinic (Data Fiduciary) must accept Terms + DPA before signup.
  const [terms, setTerms] = useState(false);
  // Ref mirror: the Google callback is registered once in a useEffect whose
  // closure would otherwise capture a stale `terms`.
  const termsRef = useRef(false);
  useEffect(() => { termsRef.current = terms; }, [terms]);

  const gsiRef = useRef(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const blur = (k) => () => setTouched((t) => ({ ...t, [k]: true }));

  const errs = {
    email: emailError(form.email),
    password: passwordError(form.password),
    clinic_name: form.clinic_name.trim().length < 2 ? "Clinic name is required" : null,
    owner_name: !form.owner_name.trim() ? "Your name is required" : null
  };
  const detailsValid = Object.values(errs).every((e) => e === null);

  useEffect(() => {
    revealStagger(pageRef.current);
  }, [step]);

  // Google signup — skips OTP (Google already authenticated the identity).
  // Requires clinic name + your name from the form above.
  useEffect(() => {
    if (step !== "details") return;
    let cancelled = false;
    const mount = () => {
      if (cancelled) return;
      if (!window.google?.accounts?.id) return void setTimeout(mount, 150);
      if (!GOOGLE_CLIENT_ID || !gsiRef.current) return;
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: async (resp) => {
          if (errs.clinic_name || errs.owner_name) {
            setTouched({ clinic_name: true, owner_name: true });
            toast.error("Fill clinic name and your name first");
            return;
          }
          if (!termsRef.current) {
            toast.error("Please accept the Terms and Data Processing Agreement first");
            return;
          }
          if (TURNSTILE_ON && !tsRef.current) {
            toast.error("Complete the verification check first");
            return;
          }
          setBusy(true);
          try {
            const me = await register({
              clinic_name: form.clinic_name.trim(),
              owner_name: form.owner_name.trim(),
              plan: form.plan,
              id_token: resp.credential,
              accepted_terms: true
            }, tsRef.current);
            toast.success("Clinic created — activate your plan in Settings to go live");
            navigate(roleHome(me.role), { replace: true });
          } catch (e) {
            toast.error(e?.response?.data?.detail ?? "Google signup failed");
          } finally {
            setBusy(false);
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
        // Cap to container width so the rendered iframe never overflows a phone.
        width: Math.min(320, gsiRef.current.offsetWidth || 320),
        text: "signup_with"
      });
    };
    mount();
    const stopWatch = watchTheme(paint); // re-render when the theme toggles
    return () => {
      cancelled = true;
      stopWatch();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, form.clinic_name, form.owner_name, form.plan]);

  const sendOtp = async () => {
    setTouched({ email: true, password: true, clinic_name: true, owner_name: true });
    if (!detailsValid) {
      toast.error("Fix the highlighted fields first");
      return;
    }
    if (!terms) {
      toast.error("Please accept the Terms and Data Processing Agreement first");
      return;
    }
    setBusy(true);
    try {
      const r = await requestOtp({ email: form.email.trim() }, ts);
      setStep("otp");
      if (r.dev_email_code) {
        setDevCode(r.dev_email_code);
        toast.info("Dev mode: code shown below (no email provider configured)");
      } else {
        toast.success("Code sent to your email");
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail ?? "Could not send code");
    } finally {
      setBusy(false);
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    if (otp.length !== 6) {
      toast.error("Enter the 6-digit code");
      return;
    }
    setBusy(true);
    try {
      const me = await register({
        clinic_name: form.clinic_name.trim(),
        owner_name: form.owner_name.trim(),
        email: form.email.trim(),
        password: form.password,
        plan: form.plan,
        email_otp: otp,
        accepted_terms: true
      }, ts);
      toast.success("Clinic created — activate your plan in Settings to go live");
      navigate(roleHome(me.role), { replace: true });
    } catch (err) {
      toast.error(err?.response?.data?.detail ?? "Registration failed");
    } finally {
      setBusy(false);
    }
  };

  const fieldErr = (k) => (touched[k] && errs[k] ? errs[k] : null);
  const checks = passwordChecks(form.password);

  return (
    <div ref={pageRef} className="min-h-dvh grid place-items-center px-4 py-12">
      <ThemeToggle float />
      <div className="w-full max-w-md">
        <Link to="/" data-reveal className="font-brand text-3xl text-teal">Vachanam</Link>
        <p data-reveal className="eyebrow mt-8">Get started · {PLANS[form.plan]} plan</p>
        <h1 data-reveal className="mt-2 font-display text-3xl font-semibold tracking-tight">
          {step === "details" ? "Create an account" : "Verify it's you"}
        </h1>
        <p data-reveal className="mt-2 font-ui text-sm text-slate">
          {step === "details"
            ? "Launch offer — first 3 months at the offer price"
            : `Enter the 6-digit code we emailed to ${form.email}.`}
        </p>

        {step === "details" ? (
          <form data-reveal className="card mt-8 space-y-4 p-6"
            onSubmit={(e) => { e.preventDefault(); sendOtp(); }}>
            <Field label="Clinic name" err={fieldErr("clinic_name")}>
              <input className="field" value={form.clinic_name} onChange={set("clinic_name")}
                onBlur={blur("clinic_name")} placeholder="Sri Dental Care" />
            </Field>
            <Field label="Email" err={fieldErr("email")}>
              <input className="field" type="email" value={form.email} onChange={set("email")}
                onBlur={blur("email")} placeholder="you@clinic.in" />
            </Field>
            <Field label="Full name" err={fieldErr("owner_name")}>
              <input className="field" value={form.owner_name} onChange={set("owner_name")}
                onBlur={blur("owner_name")} placeholder="Dr. Srinivas" />
            </Field>
            <Field label="Password" err={fieldErr("password")}>
              <PasswordField value={form.password} onChange={set("password")} autoComplete="new-password"
                onBlur={blur("password")} placeholder="Password" />
            </Field>

            <div className="rounded-xl bg-teal-mint/40 p-3">
              <p className="font-ui text-xs font-medium text-slate">Your password must contain</p>
              <ul className="mt-2 space-y-1">
                {checks.map((c) => (
                  <li key={c.label}
                    className={`flex items-center gap-2 font-ui text-xs ${c.ok ? "text-teal" : "text-slate/70"}`}>
                    <span className={`grid h-4 w-4 place-items-center rounded-full text-[10px] ${
                      c.ok ? "bg-teal text-white" : "bg-hairline text-transparent"
                    }`}>✓</span>
                    {c.label}
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <label className="label">Plan</label>
              <div className="flex gap-2">
                {Object.entries(PLANS).map(([k, v]) => (
                  <button type="button" key={k} onClick={() => setForm((f) => ({ ...f, plan: k }))}
                    className={`flex-1 rounded-xl border px-3 py-2 font-ui text-sm font-medium transition ${
                      form.plan === k ? "border-teal bg-teal-mint" : "border-hairline bg-surface hover:border-teal-light/60"
                    }`}>
                    {v}
                  </button>
                ))}
              </div>
            </div>
            {/* DPDP consent — the clinic is the Data Fiduciary; Vachanam is the
                Data Processor acting on its instructions. Server enforces too. */}
            <label className="flex items-start gap-2.5 font-ui text-xs text-ink-soft">
              <input type="checkbox" checked={terms} onChange={(e) => setTerms(e.target.checked)}
                className="mt-0.5 h-4 w-4 shrink-0 accent-teal" />
              <span>
                I agree to the{" "}
                <a href={`${API_BASE}/terms`} target="_blank" rel="noreferrer"
                  className="text-teal underline-offset-2 hover:underline">Terms of Service</a>{" "}
                and the{" "}
                <a href={`${API_BASE}/dpa`} target="_blank" rel="noreferrer"
                  className="text-teal underline-offset-2 hover:underline">Data Processing Agreement</a>.
                My clinic is the Data Fiduciary for patient data; Vachanam processes it
                only on my clinic&rsquo;s instructions ({""}
                <a href={`${API_BASE}/privacy`} target="_blank" rel="noreferrer"
                  className="text-teal underline-offset-2 hover:underline">Privacy Policy</a>).
              </span>
            </label>
            <Turnstile onToken={setTs} />
            <button className="btn-primary w-full py-3"
              disabled={busy || !terms || (TURNSTILE_ON && !ts)}>
              {busy ? "Sending code…" : "Create account"}
            </button>

            {GOOGLE_CLIENT_ID && (
              <>
                <div className="flex items-center gap-3 pt-1">
                  <span className="h-px flex-1 bg-hairline" />
                  <span className="font-ui text-xs uppercase tracking-[0.14em] text-slate">or</span>
                  <span className="h-px flex-1 bg-hairline" />
                </div>
                <div className="flex justify-center">
                  <div ref={gsiRef} className="gsi-crop" />
                </div>
                <p className="font-ui text-[11px] text-slate">
                  Google signup skips the code step — Google already verified you. Uses the
                  clinic name and your name above.
                </p>
              </>
            )}
          </form>
        ) : (
          <form data-reveal className="card mt-8 space-y-4 p-6" onSubmit={submit}>
            {devCode && (
              <div className="rounded-xl border border-gold/60 bg-gold-soft p-3 font-ui text-sm text-gold-ink">
                <p className="font-medium">Dev code (no provider configured):</p>
                <p>Email: <b className="tabular-nums">{devCode}</b></p>
              </div>
            )}
            <Field label={`Email code → ${form.email}`}>
              <input className="field tracking-[0.4em]" value={otp} inputMode="numeric"
                maxLength={6} onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
                placeholder="······" />
            </Field>
            <Turnstile onToken={setTs} />
            <button className="btn-primary w-full py-3"
              disabled={busy || (TURNSTILE_ON && !ts)}>
              {busy ? "Creating clinic…" : "Create clinic"}
            </button>
            <button type="button" className="btn-ghost w-full" onClick={() => setStep("details")}>
              Back to details
            </button>
            <button type="button" className="w-full font-ui text-sm text-teal underline-offset-4 hover:underline disabled:opacity-40"
              onClick={sendOtp} disabled={TURNSTILE_ON && !ts}>
              Resend code
            </button>
          </form>
        )}

        <p data-reveal className="mt-6 text-center font-ui text-sm text-slate">
          Already registered?{" "}
          <Link to="/login" className="font-medium text-teal underline-offset-4 hover:underline">Sign in</Link>
        </p>
      </div>
    </div>
  );
}

function Field({ label, err, children }) {
  return (
    <div>
      <label className="label">{label}</label>
      {children}
      {err && <p className="mt-1 font-ui text-xs text-danger">{err}</p>}
    </div>
  );
}
