import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { roleHome, useAuth } from "../hooks/useAuth.jsx";
import { revealStagger } from "../lib/motion.js";

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;

export default function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const pageRef = useRef(null);
  const gsiRef = useRef(null);
  const [form, setForm] = useState({
    clinic_name: "",
    owner_name: "",
    phone: "",
    email: "",
    password: ""
  });
  const [busy, setBusy] = useState(false);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  useEffect(() => {
    revealStagger(pageRef.current);
  }, []);

  // Google path still needs clinic details — validate before accepting credential
  useEffect(() => {
    let cancelled = false;
    const mount = () => {
      if (cancelled) return;
      if (!window.google?.accounts?.id) return void setTimeout(mount, 150);
      if (!GOOGLE_CLIENT_ID) return;
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: async (resp) => {
          if (form.clinic_name.trim().length < 2 || !form.owner_name.trim() || !form.phone.trim()) {
            toast.error("Fill clinic name, your name and phone first — then use Google");
            return;
          }
          await doRegister({ id_token: resp.credential });
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
  }, [form.clinic_name, form.owner_name, form.phone]);

  const doRegister = async (extra = {}) => {
    setBusy(true);
    try {
      const me = await register({
        clinic_name: form.clinic_name.trim(),
        owner_name: form.owner_name.trim(),
        phone: form.phone.trim(),
        email: form.email.trim() || null,
        password: form.password || null,
        ...extra
      });
      toast.success("Clinic created — 14-day trial started");
      navigate(roleHome(me.role), { replace: true });
    } catch (e) {
      toast.error(e?.response?.data?.detail ?? "Registration failed");
    } finally {
      setBusy(false);
    }
  };

  const submit = (e) => {
    e.preventDefault();
    if (form.password.length < 8) {
      toast.error("Password must be at least 8 characters");
      return;
    }
    doRegister();
  };

  return (
    <div ref={pageRef} className="min-h-dvh grid place-items-center px-4 py-12">
      <div className="w-full max-w-md">
        <Link to="/" data-reveal className="font-brand text-3xl text-teal">Vachanam</Link>
        <p data-reveal className="eyebrow mt-8">Start free trial</p>
        <h1 data-reveal className="mt-2 font-display text-3xl font-semibold tracking-tight">
          Register your clinic
        </h1>
        <p data-reveal className="mt-2 font-ui text-sm text-slate">
          14 days free · 1,000 call minutes · no card needed
        </p>

        <form data-reveal onSubmit={submit} className="card mt-8 space-y-4 p-6">
          <div>
            <label className="label">Clinic name</label>
            <input className="field" value={form.clinic_name} onChange={set("clinic_name")}
              placeholder="Sri Dental Care, Kukatpally" required minLength={2} />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="label">Your name</label>
              <input className="field" value={form.owner_name} onChange={set("owner_name")}
                placeholder="Dr. Srinivas" required />
            </div>
            <div>
              <label className="label">Phone</label>
              <input className="field" value={form.phone} onChange={set("phone")}
                placeholder="+91 …" inputMode="tel" required />
            </div>
          </div>
          <div>
            <label className="label">Email</label>
            <input className="field" type="email" value={form.email} onChange={set("email")}
              placeholder="you@clinic.in" required />
          </div>
          <div>
            <label className="label">Password</label>
            <input className="field" type="password" value={form.password} onChange={set("password")}
              placeholder="8+ characters" minLength={8} required />
          </div>
          <button className="btn-primary w-full py-3" disabled={busy}>
            {busy ? "Creating clinic…" : "Create clinic & start trial"}
          </button>

          <div className="flex items-center gap-3 pt-1">
            <span className="h-px flex-1 bg-hairline" />
            <span className="font-ui text-xs uppercase tracking-[0.14em] text-slate">or</span>
            <span className="h-px flex-1 bg-hairline" />
          </div>
          <div ref={gsiRef} className="flex justify-center" />
          <p className="font-ui text-[11px] text-slate">
            Google signup uses the clinic name, your name and phone from above.
          </p>
        </form>

        <p data-reveal className="mt-6 text-center font-ui text-sm text-slate">
          Already registered?{" "}
          <Link to="/login" className="font-medium text-teal underline-offset-4 hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
