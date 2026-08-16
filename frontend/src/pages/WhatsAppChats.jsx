import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import PageHeader from "../components/PageHeader.jsx";
import { fetchWaChat, fetchWaChats, fetchWaConnection } from "../api/client.js";
import { useAuth } from "../hooks/useAuth.jsx";
import WhatsAppComingSoon from "../components/WhatsAppComingSoon.jsx";
import { WHATSAPP_SELF_SERVE_LIVE } from "../lib/plans.js";

// Thread list on the left, transcript on the right — the shape everyone
// already knows from every messaging app, so nothing here needs explaining.
//
// Read-only by design. Under Coexistence the clinic's own WhatsApp app stays
// live on the same number, so staff already have somewhere to type: their
// phone. A reply box here would mean two answers to one patient message.

function timeLabel(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return sameDay
    ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString([], { day: "numeric", month: "short" });
}

function Bubble({ turn }) {
  const isBot = turn.role === "bot";
  return (
    <div className={`flex ${isBot ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[80%] rounded-2xl px-3.5 py-2 ${
        isBot ? "bg-teal text-white" : "bg-pill text-ink"
      }`}>
        <p className="whitespace-pre-wrap break-words font-ui text-sm">{turn.text}</p>
        <p className={`mt-1 font-ui text-[11px] ${isBot ? "text-white/70" : "text-slate"}`}>
          {timeLabel(turn.at)}
        </p>
      </div>
    </div>
  );
}

export function WhatsAppChatsLive() {
  const { branchId } = useAuth();
  const [selected, setSelected] = useState(null);

  const connection = useQuery({
    queryKey: ["wa-connection", branchId],
    queryFn: () => fetchWaConnection(branchId),
    enabled: Boolean(branchId),
    refetchInterval: 5000,
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: "always",
  });
  // Fail closed. Until the server positively confirms this branch's number
  // is connected, no patient conversation text is mounted from browser cache.
  const connected = (
    connection.isFetchedAfterMount && connection.data?.connected === true
  );

  useEffect(() => {
    if (!connected) setSelected(null);
  }, [connected]);

  const { data: chats = [], isLoading, error } = useQuery({
    queryKey: ["wa-chats", branchId],
    queryFn: () => fetchWaChats(branchId),
    enabled: Boolean(branchId && connected),
    // Patients message while the page is open; a stale list looks broken.
    refetchInterval: 30000,
  });

  const { data: thread } = useQuery({
    queryKey: ["wa-chat", branchId, selected],
    queryFn: () => fetchWaChat(branchId, selected),
    enabled: Boolean(branchId && connected && selected),
    refetchInterval: 15000,
  });

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="WhatsApp" title="Chats"
        sub="What patients asked your AI assistant on WhatsApp, and how it replied. Read-only — reply from your own WhatsApp app if you need to step in." />

      {connection.isLoading && (
        <div className="card p-5 font-ui text-sm text-slate" role="status">
          Checking WhatsApp connection...
        </div>
      )}

      {!connection.isLoading && (connection.error || !connected) && (
        <div className="card p-5" data-testid="wa-chats-disconnected">
          <p className="font-ui text-sm font-semibold text-ink">
            WhatsApp is disconnected
          </p>
          <p className="mt-1 font-ui text-sm text-slate">
            Connect this clinic's WhatsApp number to receive new messages and
            view its conversations. Cached chats are never shown while the
            connection is off.
          </p>
        </div>
      )}

      {connected && (
      <div className="grid gap-6 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
        {/* Left — thread list */}
        <div className="card divide-y divide-hairline overflow-hidden">
          {isLoading && <p className="p-5 font-ui text-sm text-slate">Loading chats…</p>}
          {error && (
            <p className="p-5 font-ui text-sm text-danger">
              {error?.response?.data?.detail ?? "Could not load chats."}
            </p>
          )}
          {!isLoading && !error && chats.length === 0 && (
            <p className="p-5 font-ui text-sm text-slate">
              No WhatsApp conversations yet. Once your number is connected,
              every patient thread appears here.
            </p>
          )}
          {chats.map((c) => (
            <button key={c.phone} type="button"
              data-testid={`wa-chat-${c.phone_last4}`}
              onClick={() => setSelected(c.phone)}
              className={`block w-full px-5 py-3.5 text-left transition ${
                selected === c.phone ? "bg-pill" : "hover:bg-pill/60"
              }`}>
              <div className="flex items-baseline justify-between gap-3">
                <p className="font-ui text-sm font-semibold text-ink">
                  <span className="numeral">···{c.phone_last4}</span>
                </p>
                <span className="shrink-0 font-ui text-xs text-slate">
                  {timeLabel(c.last_at || c.updated_at)}
                </span>
              </div>
              <p className="truncate font-ui text-xs text-slate">
                {c.last_role === "bot" ? "You: " : ""}{c.last_text || "—"}
              </p>
            </button>
          ))}
        </div>

        {/* Right — transcript */}
        <div className="card p-5">
          {!selected ? (
            <p className="font-ui text-sm text-slate">
              Pick a conversation to read it.
            </p>
          ) : (
            <div className="space-y-3">
              <p className="font-ui text-sm font-semibold text-ink">
                <span className="numeral">···{thread?.phone_last4 ?? ""}</span>
              </p>
              {(thread?.turns ?? []).length === 0 ? (
                <p className="font-ui text-sm text-slate">
                  Nothing stored for this conversation.
                </p>
              ) : (
                (thread?.turns ?? []).map((t, i) => (
                  <Bubble key={`${t.at ?? ""}-${i}`} turn={t} />
                ))
              )}
              <p className="pt-2 font-ui text-xs text-slate">
                Only recent messages are kept — older ones are deleted
                automatically.
              </p>
            </div>
          )}
        </div>
      </div>
      )}
    </div>
  );
}

export default function WhatsAppChats() {
  return WHATSAPP_SELF_SERVE_LIVE ? <WhatsAppChatsLive /> : <WhatsAppComingSoon />;
}
