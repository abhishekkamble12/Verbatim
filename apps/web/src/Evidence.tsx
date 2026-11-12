import { useState } from "react";
import { api } from "./api";
import { Badge } from "./Claim";
import type { ClaimItem } from "./types";

function OpenPdf({ sourceId, page }: { sourceId: string; page: number | null }) {
  const [error, setError] = useState<string | null>(null);
  const open = async () => {
    setError(null);
    try {
      const { url } = await api.sourceUrl(sourceId);
      window.open(page ? `${url}#page=${page}` : url, "_blank", "noopener");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <>
      <button type="button" className="link" onClick={open}>Open PDF</button>
      {error && <span className="error-inline" role="alert"> {error}</span>}
    </>
  );
}

const words = (s: string) => new Set((s.toLowerCase().match(/\w+/g) ?? []).filter((w) => w.length > 2 || /\d/.test(w)));

/** Display aid only: the sentence of the quote sharing the most words with the claim. The verifier checked the whole quote. */
export function closestSentence(quote: string, claim: string): { before: string; match: string; after: string } | null {
  const parts = quote.split(/(?<=[.!?]\s+)(?=\S)/); // split after "." + space, so "47.5" stays whole
  if (parts.length < 2) return null;
  const want = words(claim);
  const scores = parts.map((p) => [...words(p)].filter((w) => want.has(w)).length);
  const best = scores.indexOf(Math.max(...scores));
  if (scores[best] === 0) return null;
  return { before: parts.slice(0, best).join(""), match: parts[best], after: parts.slice(best + 1).join("") };
}

function Quote({ quote, claim }: { quote: string; claim: string }) {
  const p = closestSentence(quote, claim);
  if (!p) return <blockquote>“{quote}”</blockquote>;
  return <blockquote>“{p.before}<mark title="Closest sentence to the claim">{p.match}</mark>{p.after}”</blockquote>;
}

export function Evidence({ claim }: { claim: ClaimItem | null }) {
  if (!claim) {
    return <p className="muted">Select a claim to see the exact quote it rests on.</p>;
  }
  const cited = claim.citations.filter((c) => c.quote);
  return (
    <div>
      <p className="evidence-claim"><Badge status={claim.support_status} /> {claim.text}</p>
      {cited.length === 0 && <p className="muted">This claim has no supporting quote.</p>}
      {cited.length > 0 && <p className="muted">Highlighted: the sentence closest to the claim. The check covers the whole quote.</p>}
      {cited.map((c) => (
        <figure className="quote" key={`${c.chunk_id}-${c.page_number}`}>
          <Quote quote={c.quote ?? ""} claim={claim.text} />
          <figcaption>
            {c.source_title ?? "Source"}{c.page_number ? ` · p. ${c.page_number}` : ""}
            {c.source_id && <> · <OpenPdf sourceId={c.source_id} page={c.page_number} /></>}
          </figcaption>
        </figure>
      ))}
    </div>
  );
}
