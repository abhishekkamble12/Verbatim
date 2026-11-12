import { api } from "./api";
import { useLoad } from "./hooks";

export function Trace({ reportId }: { reportId: string }) {
  const t = useLoad(() => api.trace(reportId), [reportId]);
  if (t.loading) return <p className="muted">Loading trace…</p>;
  if (t.error) return <p className="error" role="alert">{t.error}</p>;
  const steps = t.data?.agent_steps ?? [];
  if (steps.length === 0) return <p className="muted">No steps were recorded.</p>;

  // Totals are plain sums of what the API returned.
  const tokens = steps.reduce((n, s) => n + (s.tokens ?? 0), 0);
  const ms = steps.reduce((n, s) => n + (s.latency_ms ?? 0), 0);
  return (
    <div className="table-wrap">
      <table>
        <caption className="sr-only">Report agent steps</caption>
        <thead>
          <tr><th>Step</th><th>Tool</th><th className="num">Tokens</th><th className="num">Time (ms)</th></tr>
        </thead>
        <tbody>
          {steps.map((s, n) => (
            <tr key={n}>
              <td>{s.state}</td>
              <td>
                {s.tool ?? "—"}
                {(s.tool_input || s.tool_output) && (
                  <details>
                    <summary>Details</summary>
                    {s.tool_input && <pre>in: {s.tool_input}</pre>}
                    {s.tool_output && <pre>out: {s.tool_output}</pre>}
                  </details>
                )}
              </td>
              <td className="num">{s.tokens ?? "—"}</td>
              <td className="num">{s.latency_ms ?? "—"}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr><th colSpan={2}>Total</th><td className="num">{tokens}</td><td className="num">{ms}</td></tr>
        </tfoot>
      </table>
    </div>
  );
}
