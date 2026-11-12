import type { Usage } from "./types";

/** Formats what the API recorded; nothing is estimated in the browser. */
export function formatCost(usd: number): string {
  if (usd === 0) return "$0";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

export function Cost({ usage }: { usage: Usage | null | undefined }) {
  if (!usage) return null;
  const tokens = usage.prompt_tokens + usage.completion_tokens;
  return (
    <p className="cost" title="LLM calls at list price; embeddings not included">
      {tokens.toLocaleString()} tokens · est. {formatCost(usage.cost_usd)}
    </p>
  );
}
