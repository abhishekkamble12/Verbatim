import type { ClaimItem, SupportStatus } from "./types";

// Colour is never the only signal: every badge carries an icon and a word.
const BADGE: Record<SupportStatus, { icon: string; label: string }> = {
  verified: { icon: "✓", label: "Verified" },
  partial: { icon: "◐", label: "Partial" },
  rejected: { icon: "✕", label: "Rejected" },
  pending: { icon: "…", label: "Unchecked" },
};

export function Badge({ status }: { status: SupportStatus }) {
  const b = BADGE[status] ?? BADGE.pending;
  return (
    <span className={`badge badge-${status}`}>
      <span aria-hidden="true">{b.icon}</span> {b.label}
    </span>
  );
}

/** Counts the statuses the API returned; any rejected claim marks the whole answer. */
export function summarize(claims: ClaimItem[]): { text: string; tone: "ok" | "warn" | "bad" } | null {
  if (claims.length === 0) return null;
  const count = (s: SupportStatus) => claims.filter((c) => c.support_status === s).length;
  const [verified, partial, rejected] = [count("verified"), count("partial"), count("rejected")];
  const text = [
    `${verified} of ${claims.length} claims verified`,
    partial && `${partial} partial`,
    rejected && `${rejected} rejected`,
  ].filter(Boolean).join(" · ");
  return { text, tone: rejected ? "bad" : verified === claims.length ? "ok" : "warn" };
}

export function Summary({ claims }: { claims: ClaimItem[] }) {
  const s = summarize(claims);
  return s && <p className={`summary summary-${s.tone}`}>{s.text}</p>;
}

export function Claim({ claim, selected, onSelect }: { claim: ClaimItem; selected: boolean; onSelect: () => void }) {
  return (
    <li>
      <button type="button" className={`claim claim-${claim.support_status}`} aria-pressed={selected} onClick={onSelect}>
        <Badge status={claim.support_status} />
        <span className="claim-text">{claim.text}</span>
      </button>
      {claim.support_status === "rejected" && claim.rejection_reason && (
        <p className="claim-reason">Why it was rejected: {claim.rejection_reason}</p>
      )}
    </li>
  );
}
