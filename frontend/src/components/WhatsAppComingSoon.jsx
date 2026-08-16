import { HourglassMedium, ShieldCheck, WhatsappLogo } from "@phosphor-icons/react";
import PageHeader from "./PageHeader.jsx";

export default function WhatsAppComingSoon() {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <PageHeader eyebrow="WhatsApp" title="WhatsApp is coming soon"
        sub="Vachanam is completing Meta Tech Provider approval before clinic onboarding opens." />

      <section className="card overflow-hidden" aria-labelledby="whatsapp-review-status">
        <div className="flex flex-col gap-6 p-6 sm:flex-row sm:items-start sm:p-8">
          <span className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-pill text-teal" aria-hidden>
            <WhatsappLogo size={30} weight="duotone" />
          </span>
          <div className="min-w-0">
            <span className="chip-muted inline-flex items-center gap-1.5">
              <HourglassMedium size={14} weight="bold" /> Meta review in progress
            </span>
            <h2 id="whatsapp-review-status" className="mt-3 font-display text-xl font-semibold text-ink">
              Clinic connections are not open yet
            </h2>
            <p className="mt-2 max-w-2xl font-ui text-sm leading-6 text-slate">
              We will enable official clinic onboarding only after approval is complete.
              No WhatsApp add-on payment or number connection can be started before then.
            </p>
          </div>
        </div>
        <div className="border-t border-hairline bg-pill px-6 py-4 sm:px-8">
          <p className="flex items-start gap-2 font-ui text-sm text-ink-soft">
            <ShieldCheck className="mt-0.5 shrink-0 text-teal" size={18} weight="duotone" />
            Voice calling, appointments, reminders and the clinic dashboard continue to work normally.
          </p>
        </div>
      </section>
    </div>
  );
}
