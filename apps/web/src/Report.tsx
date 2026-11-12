import { useEffect, useRef, useState } from "react";
import { api, watchJob } from "./api";
import { Claim, Summary } from "./Claim";
import { Cost } from "./Cost";
import { useLoad } from "./hooks";
import { Trace } from "./Trace";
import type { ClaimItem } from "./types";

export function Report({ notebookId, selected, onSelect }: {
  notebookId: string;
  selected: ClaimItem | null;
  onSelect: (c: ClaimItem) => void;
}) {
  const [question, setQuestion] = useState("");
  const [reportId, setReportId] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const stop = useRef<() => void>();
  useEffect(() => () => stop.current?.(), []);

  async function start() {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true); setError(null); setReportId(null); setStatus("Report queued…");
    try {
      const { job_id } = await api.createReport(notebookId, q);
      stop.current = watchJob(job_id, (j) => {
        if (j.state === "running") setStatus("Researching your sources…");
        if (j.state === "failed") { setStatus(""); setError("The report job failed."); setBusy(false); }
        if (j.state === "completed") { setStatus(""); setReportId(j.report_id ?? null); setBusy(false); }
      }, (e) => { setError(e.message); setStatus(""); setBusy(false); });
    } catch (e) {
      setError((e as Error).message); setStatus(""); setBusy(false);
    }
  }

  return (
    <section aria-label="Report" className="report">
      <form className="composer" onSubmit={(e) => { e.preventDefault(); void start(); }}>
        <label className="sr-only" htmlFor="rq">Report question</label>
        <textarea id="rq" rows={2} value={question} maxLength={2000} placeholder="What should the report cover?"
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void start(); } }} />
        <button type="submit" disabled={busy || !question.trim()}>Create report</button>
      </form>
      <p className="sr-only" aria-live="polite">{status}</p>
      {status && <p className="muted">{status}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {!reportId && !status && !error && (
        <p className="muted empty">A report runs a bounded research agent over your sources and keeps only verified claims.</p>
      )}
      {reportId && <Finished reportId={reportId} selected={selected} onSelect={onSelect} />}
    </section>
  );
}

function Finished({ reportId, selected, onSelect }: {
  reportId: string;
  selected: ClaimItem | null;
  onSelect: (c: ClaimItem) => void;
}) {
  const r = useLoad(() => api.report(reportId), [reportId]);
  const [trace, setTrace] = useState(false);
  if (r.loading) return <p className="muted">Loading report…</p>;
  if (r.error || !r.data) return <p className="error" role="alert">{r.error}</p>;
  const report = r.data;
  return (
    <article>
      <h2>{report.question}</h2>
      <Summary claims={report.claims} />
      {report.is_partial && (
        <p className="banner" role="status">
          Partial report: the agent hit its budget before finishing, so some questions may be missing.
        </p>
      )}
      {report.claims.length === 0
        ? <p className="bubble abstain">Not enough evidence in your sources to answer this.</p>
        : <ul className="claims">{report.claims.map((c, n) => (
            <Claim key={n} claim={c} selected={selected === c} onSelect={() => onSelect(c)} />
          ))}</ul>}
      <Cost usage={report.usage} />
      <button type="button" className="secondary" aria-expanded={trace} onClick={() => setTrace(!trace)}>
        {trace ? "Hide trace" : "Show trace"}
      </button>
      {trace && <Trace reportId={reportId} />}
    </article>
  );
}
