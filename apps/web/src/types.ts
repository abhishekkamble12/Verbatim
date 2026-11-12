// Mirrors the API responses in services/api/main.py. Nothing here is computed by the UI.
export type SupportStatus = "pending" | "verified" | "partial" | "rejected";

export interface Citation {
  chunk_id: string;
  quote: string | null;
  page_number: number | null;
  source_id: string | null;
  source_title: string | null;
}

export interface ClaimItem {
  text: string;
  citations: Citation[];
  support_status: SupportStatus;
  rejection_reason: string | null;
}

export interface Notebook { id: string; title: string; description: string | null; created_at: string }
export interface Source { id: string; title: string; source_type: string; created_at: string }
export interface PendingUpload { job_id: string; filename: string | null; state: string }
export interface SourceList { sources: Source[]; pending_uploads: PendingUpload[] }

/** LLM tokens and list-price cost, as recorded by the API. Embeddings are not included. */
export interface Usage { prompt_tokens: number; completion_tokens: number; cost_usd: number }

export interface ChatAnswer {
  conversation_id: string;
  original_query: string;
  rewritten_query: string | null;
  query_rewritten: boolean;
  answer: string;
  claims: ClaimItem[];
  insufficient_evidence: boolean;
  usage: Usage;
}

export interface Conversation { id: string; title: string; created_at: string }
export interface StoredMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  claims: ClaimItem[];
  usage: Usage | null;
}

export interface Job {
  id: string;
  job_type: string;
  state: "queued" | "running" | "completed" | "failed";
  retries: number;
  report_id?: string | null;
}
export interface Report {
  id: string;
  question: string;
  claims: ClaimItem[];
  is_partial: boolean;
  usage: Usage | null;
}
export interface TraceStep {
  state: string;
  tool: string | null;
  tool_input: string | null;
  tool_output: string | null;
  tokens: number | null;
  latency_ms: number | null;
}
