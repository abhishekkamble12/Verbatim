import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Claim, Summary } from "./Claim";
import { Cost } from "./Cost";
import { useLoad } from "./hooks";
import type { ChatAnswer, ClaimItem, StoredMessage, Usage } from "./types";

type Item =
  | { kind: "user"; text: string }
  | { kind: "live"; answer: ChatAnswer }
  | { kind: "stored"; msg: StoredMessage }
  | { kind: "error"; text: string };

export function Chat({ notebookId, selected, onSelect }: {
  notebookId: string;
  selected: ClaimItem | null;
  onSelect: (c: ClaimItem) => void;
}) {
  const convs = useLoad(() => api.conversations(notebookId), [notebookId]);
  const [convId, setConvId] = useState<string | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  // Open the most recent conversation once the list first arrives.
  useEffect(() => {
    if (convs.data && convs.data.length > 0 && convId === null && items.length === 0) void open(convs.data[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [convs.data]);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "end" }); }, [items]);

  async function open(id: string) {
    setConvId(id);
    try {
      const msgs = await api.messages(id);
      setItems(msgs.map((m): Item => (m.role === "user" ? { kind: "user", text: m.content } : { kind: "stored", msg: m })));
    } catch (e) {
      setItems([{ kind: "error", text: (e as Error).message }]);
    }
  }

  async function send() {
    const query = text.trim();
    if (!query || busy) return;
    setText("");
    setBusy(true);
    setItems((i) => [...i, { kind: "user", text: query }]);
    try {
      const answer = await api.chat(notebookId, query, convId);
      setConvId(answer.conversation_id);
      setItems((i) => [...i, { kind: "live", answer }]);
      convs.reload();
    } catch (e) {
      setItems((i) => [...i, { kind: "error", text: (e as Error).message }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Chat" className="chat">
      <div className="chat-bar">
        <label>
          <span className="sr-only">Conversation</span>
          <select
            value={convId ?? ""}
            onChange={(e) => {
              if (e.target.value) void open(e.target.value);
              else { setConvId(null); setItems([]); }
            }}
          >
            <option value="">New chat</option>
            {convs.data?.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
          </select>
        </label>
      </div>

      <div className="thread" aria-live="polite">
        {items.length === 0 && !busy && (
          <p className="muted empty">
            Ask a question about your sources. Every claim in the answer is checked against an exact quote.
          </p>
        )}
        {items.map((it, n) => <Turn key={n} item={it} selected={selected} onSelect={onSelect} />)}
        {busy && <p className="muted">Checking claims against your sources…</p>}
        <div ref={end} />
      </div>

      <form className="composer" onSubmit={(e) => { e.preventDefault(); void send(); }}>
        <label className="sr-only" htmlFor="q">Your question</label>
        <textarea
          id="q" rows={2} value={text} placeholder="Ask about your sources…" maxLength={2000}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }}
        />
        <button type="submit" disabled={busy || !text.trim()}>Ask</button>
      </form>
    </section>
  );
}

function Turn({ item, selected, onSelect }: {
  item: Item;
  selected: ClaimItem | null;
  onSelect: (c: ClaimItem) => void;
}) {
  if (item.kind === "user") return <p className="bubble user">{item.text}</p>;
  if (item.kind === "error") return <p className="bubble error" role="alert">{item.text}</p>;

  if (item.kind === "stored") {
    const m = item.msg;
    // A stored answer with no claims is an abstention (answers with content always carry claims).
    if (m.claims.length === 0) return <Abstain usage={m.usage} />;
    return (
      <div className="bubble assistant">
        <Summary claims={m.claims} />
        <ul className="claims">
          {m.claims.map((c, n) => <Claim key={n} claim={c} selected={selected === c} onSelect={() => onSelect(c)} />)}
        </ul>
        <Cost usage={m.usage} />
      </div>
    );
  }

  const a = item.answer;
  if (a.insufficient_evidence) {
    return <Abstain usage={a.usage} searched={a.query_rewritten ? a.rewritten_query : null} />;
  }
  return (
    <div className="bubble assistant">
      <Summary claims={a.claims} />
      {a.query_rewritten && a.rewritten_query && <p className="muted">Searched for: “{a.rewritten_query}”</p>}
      <ul className="claims">
        {a.claims.map((c, n) => <Claim key={n} claim={c} selected={selected === c} onSelect={() => onSelect(c)} />)}
      </ul>
      {a.claims.length === 0 && <p>{a.answer}</p>}
      <Cost usage={a.usage} />
    </div>
  );
}

function Abstain({ usage, searched }: { usage: Usage | null; searched?: string | null }) {
  return (
    <div className="bubble abstain" role="status">
      <strong>Not enough evidence in your sources</strong>
      <p>CiteGuard would rather say nothing than guess. Try a more specific question, or add a source that covers this.</p>
      {searched && <p className="muted">Searched for: “{searched}”</p>}
      <Cost usage={usage} />
    </div>
  );
}
