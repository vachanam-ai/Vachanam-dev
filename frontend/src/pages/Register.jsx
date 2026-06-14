import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { requestOtp } from "../api/client.js";
import { roleHome, useAuth } from "../hooks/useAuth.jsx";
import { revealStagger } from "../lib/motion.js";

const PLANS = { solo: "Solo", clinic: "Clinic", multi: "Multi" };
const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;

// Mirror backend validators so the user gets instant, identical feedback.
const phoneError = (v) => {
  const d = v.replace(/[\s\-()]/g, "").replace(/^\+?91/, "").replace(/^0/, "");
  if (!d) return "Phone is required";
  if (!/^[6-9]\d{9}$/.test(d)) return "Enter a valid 10-digit Indian mobile (starts 6–9)";
  return null;
};
const emailError = (v) => {
  if (!v) return "Email is required";
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v) || v.includes("..")) return "Enter a valid email";
  return null;
};
const passwordError = (v) => {
  if (!v || v.length < 8) return "At least 8 characters";
  if (/^\d+$/.test(v)) return "Cannot be only numbers";
  if (!/[A-Za-z]/.test(v)) return "Add at least one letter";
  if (!/\d/.test(v)) return "Add at least one number";
  return null;
};

export default function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const pageRef = useRef(null);
  const [params] = useSearchParams();
  const planParam = params.get("plan");

  const [form, setForm] = useState({
    clinic_name: "",
    owner_name: "",
    phone: "",
    email: "",
    password: "",
    plan: PLANS[planParam] ? planParam : "clinic"
  });
  const [touched, setTouched] = useState({});
  const [step, setStep] = useState("details"); // details | otp
  const [otp, setOtp] = useState({ phone: "", email: "" });
  const [devCodes, setDevCodes] = useState(null);
  const [busy, setBusy] = useState(false);

  const gsiRef = useRef(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const blur = (k) => () => setTouched((t) => ({ ...t, [k]: true }));

  const errs = {
    phone: phoneError(form.phone),
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
  // Requires clinic name + your name + valid phone from the form above.
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
          if (errs.clinic_name || errs.owner_name || errs.phone) {
            setTouched({ clinic_name: true, owner_name: true, phone: true });
            toast.error("Fill clinic name, your name and a valid phone first");
            return;
          }
          setBusy(true);
          try {
            const me = await register({
              clinic_name: form.clinic_name.trim(),
              owner_name: form.owner_name.trim(),
              phone: form.phone.trim(),
              plan: form.plan,
              id_token: resp.credential
            });
            toast.success("Clinic created — 14-day trial started");
            navigate(roleHome(me.role), { replace: true });
          } catch (e) {
            toast.error(e?.response?.data?.detail ?? "Google signup failed");
          } finally {
            setBusy(false);
          }
        }
      });
      window.google.accounts.id.renderButton(gsiRef.current, {
        theme: "outline",
        size: "large",
        shape: "pill",
        width: 320,
        text: "signup_with"
      });
    };
    mount();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, form.clinic_name, form.owner_name, form.phone, form.plan]);

  const sendOtp = async () => {
    setTouched({ phone: true, email: true, password: true, clinic_name: true, owner_name: true });
    if (!detailsValid) {
      toast.error("Fix the highlighted fields first");
      return;
    }
    setBusy(true);
    try {
      const r = await requestOtp({ phone: form.phone });
      setStep("otp");
      if (r.dev_phone_code) {
        setDevCodes({ phone: r.dev_phone_code });
        toast.info("Dev mode: code shown below (no SMS provider configured)");
      } else {
        toast.success("Code sent to your phone");
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail ?? "Could not send code");
    } finally {
      setBusy(false);
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    if (otp.phone.length !== 6) {
      toast.error("Enter the 6-digit code");
      return;
    }
    setBusy(true);
    try {
      const me = await register({
        clinic_name: form.clinic_name.trim(),
        owner_name: form.owner_name.trim(),
        phone: form.phone.trim(),
        email: form.email.trim(),
        password: form.password,
        plan: form.plan,
        phone_otp: otp.phone
      });
      toast.success("Clinic created — 14-day trial started");
      navigate(roleHome(me.role), { replace: true });
    } catch (err) {
      toast.error(err?.response?.data?.detail ?? "Registration failed");
    } finally {
      setBusy(false);
    }
  };

  const fieldErr = (k) => (touched[k] && errs[k] ? errs[k] : null);

  return (
    <div ref={pageRef} className="min-h-dvh grid place-items-center px-4 py-12">
      <div className="w-full max-w-md">
        <Link to="/" data-reveal className="font-brand text-3xl text-teal">Vachanam</Link>
        <p data-reveal className="eyebrow mt-8">Start free trial · {PLANS[form.plan]} plan</p>
        <h1 data-reveal className="mt-2 font-display text-3xl font-semibold tracking-tight">
          {step === "details" ? "Register your clinic" : "Verify it's you"}
        </h1>
        <p data-reveal className="mt-2 font-ui text-sm text-slate">
          {step === "details"
            ? "14 days free · 1,000 call minutes · no card needed"
            : "Enter the 6-digit code we sent to your phone."}
        </p>

        {step === "details" ? (
          <form data-reveal className="card mt-8 space-y-4 p-6"
            onSubmit={(e) => { e.preventDefault(); sendOtp(); }}>
            <Field label="Clinic name" err={fieldErr("clinic_name")}>
              <input className="field" value={form.clinic_name} onChange={set("clinic_name")}
                onBlur={blur("clinic_name")} placeholder="Sri Dental Care, Kukatpally" />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Your name" err={fieldErr("owner_name")}>
                <input className="field" value={form.owner_name} onChange={set("owner_name")}
                  onBlur={blur("owner_name")} placeholder="Dr. Srinivas" />
              </Field>
              <Field label="Phone" err={fieldErr("phone")}>
                <input className="field" value={form.phone} onChange={set("phone")}
                  onBlur={blur("phone")} placeholder="98765 43210" inputMode="tel" />
              </Field>
            </div>
            <Field label="Email" err={fieldErr("email")}>
              <input className="field" type="email" value={form.email} onChange={set("email")}
                onBlur={blur("email")} placeholder="you@clinic.in" />
            </Field>
            <Field label="Password" err={fieldErr("password")}>
              <input className="field" type="password" value={form.password} onChange={set("password")}
                onBlur={blur("password")} placeholder="8+ chars, letters + numbers" />
            </Field>
            <div>
              <label className="label">Plan</label>
              <div className="flex gap-2">
                {Object.entries(PLANS).map(([k, v]) => (
                  <button type="button" key={k} onClick={() => setForm((f) => ({ ...f, plan: k }))}
                    className={`flex-1 rounded-xl border px-3 py-2 font-ui text-sm font-medium transition ${
                      form.plan === k ? "border-teal bg-teal-mint" : "border-hairline bg-white hover:border-teal-light/60"
                    }`}>
                    {v}
                  </button>
                ))}
              </div>
            </div>
            <button className="btn-primary w-full py-3" disabled={busy}>
              {busy ? "Sending code…" : "Verify phone"}
            </button>

            {GOOGLE_CLIENT_ID && (
              <>
                <div className="flex items-center gap-3 pt-1">
                  <span className="h-px flex-1 bg-hairline" />
                  <span className="font-ui text-xs uppercase tracking-[0.14em] text-slate">or</span>
                  <span className="h-px flex-1 bg-hairline" />
                </div>
                <div ref={gsiRef} className="flex justify-center" />
                <p className="font-ui text-[11px] text-slate">
                  Google signup skips the code step — Google already verified you. Uses the
                  clinic name, your name and phone above.
                </p>
              </>
            )}
          </form>
        ) : (
          <form data-reveal className="card mt-8 space-y-4 p-6" onSubmit={submit}>
            {devCodes && (
              <div className="rounded-xl border border-gold/60 bg-gold-soft p-3 font-ui text-sm text-gold-ink">
                <p className="font-medium">Dev code (no provider configured):</p>
                <p>Phone: <b className="tabular-nums">{devCodes.phone ?? "—"}</b></p>
              </div>
            )}
            <Field label={`SMS code → ${form.phone}`}>
              <input className="field tracking-[0.4em]" value={otp.phone} inputMode="numeric"
                maxLength={6} onChange={(e) => setOtp((o) => ({ ...o, phone: e.target.value.replace(/\D/g, "") }))}
                placeholder="······" />
            </Field>
            <button className="btn-primary w-full py-3" disabled={busy}>
              {busy ? "Creating clinic…" : "Create clinic & start trial"}
            </button>
            <button type="button" className="btn-ghost w-full" onClick={() => setStep("details")}>
              Back to details
            </button>
            <button type="button" className="w-full font-ui text-sm text-teal underline-offset-4 hover:underline"
              onClick={sendOtp}>
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
