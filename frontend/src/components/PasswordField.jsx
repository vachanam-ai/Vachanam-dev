import { useState } from "react";
import { Eye, EyeSlash } from "@phosphor-icons/react";

// Password input with a show/hide eye toggle. Drop-in for `<input className="field" type="password" .../>`
// — spreads any extra props (value, onChange, required, placeholder, autoComplete…) onto the input.
export default function PasswordField({ className = "field", ...props }) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <input {...props} className={`${className} pr-10`} type={show ? "text" : "password"} />
      <button
        type="button"
        onClick={() => setShow((s) => !s)}
        aria-label={show ? "Hide password" : "Show password"}
        title={show ? "Hide password" : "Show password"}
        className="absolute inset-y-0 right-0 grid w-10 place-items-center text-slate hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-light/40 rounded-r-lg"
      >
        {show ? <EyeSlash size={18} weight="duotone" aria-hidden /> : <Eye size={18} weight="duotone" aria-hidden />}
      </button>
    </div>
  );
}
