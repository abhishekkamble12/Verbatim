import { useEffect, useRef, useState } from "react";
import { api, uploadPdf, watchJob } from "./api";
import { useLoad } from "./hooks";

const STATE_LABEL: Record<string, string> = {
  queued: "Waiting to process…", running: "Processing…", failed: "Failed to process",
};

export function Sources({ notebookId }: { notebookId: string }) {
  const list = useLoad(() => api.sources(notebookId), [notebookId]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [dragging, setDragging] = useState(false);
  const stops = useRef<(() => void)[]>([]);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => () => stops.current.forEach((s) => s()), []);

  // Resume progress for uploads that were already in flight when the page opened.
  useEffect(() => {
    for (const p of list.data?.pending_uploads ?? []) {
      if (p.state === "failed") continue;
      stops.current.push(watchJob(p.job_id, (j) => { if (j.state === "completed") list.reload(); }, () => {}));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list.data?.pending_uploads.map((p) => p.job_id).join(",")]);

  async function onFiles(files: FileList | null) {
    for (const f of Array.from(files ?? [])) await onFile(f);
  }

  async function onFile(file: File) {
    setError(null);
    if (!file.name.toLowerCase().endsWith(".pdf")) { setError(`${file.name}: only PDF files are supported.`); return; }
    setUploading(true);
    setStatus(`Uploading ${file.name}…`);
    try {
      const jobId = await uploadPdf(notebookId, file);
      list.reload();
      stops.current.push(watchJob(jobId, (j) => {
        if (j.state === "completed") setStatus(`${file.name} is ready.`);
        if (j.state === "failed") setStatus(`${file.name} could not be processed.`);
        if (j.state === "completed" || j.state === "failed") list.reload();
      }, (e) => setError(e.message)));
    } catch (e) {
      setError((e as Error).message);
      setStatus("");
    } finally {
      setUploading(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <section aria-label="Sources">
      <h2>Sources</h2>
      <label
        className={`dropzone${dragging ? " dragging" : ""}${uploading ? " busy" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); void onFiles(e.dataTransfer.files); }}
      >
        <input ref={input} type="file" accept="application/pdf,.pdf" multiple disabled={uploading} className="sr-only"
               onChange={(e) => void onFiles(e.target.files)} />
        <span className="dropzone-button">{uploading ? "Uploading…" : "Choose PDF"}</span>
        <span className="muted">or drop PDFs here</span>
      </label>
      <p className="sr-only" aria-live="polite">{status}</p>
      {status && <p className="muted">{status}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {list.loading && !list.data && <p className="muted">Loading sources…</p>}
      {list.error && <p className="error" role="alert">{list.error} <button type="button" className="link" onClick={list.reload}>Retry</button></p>}
      {list.data && list.data.sources.length === 0 && list.data.pending_uploads.length === 0 && (
        <p className="muted">Upload a PDF to start.</p>
      )}
      <ul className="plain">
        {list.data?.pending_uploads.map((p) => (
          <li key={p.job_id} className={`src src-${p.state === "failed" ? "failed" : "pending"}`}>
            <span aria-hidden="true" className="src-icon">{p.state === "failed" ? "✕" : "⏳"}</span>
            <span>{p.filename ?? "Upload"} <span className="muted">{STATE_LABEL[p.state] ?? p.state}</span></span>
          </li>
        ))}
        {list.data?.sources.map((s) => (
          <li key={s.id} className="src src-ready">
            <span aria-hidden="true" className="src-icon">✓</span>
            <span>{s.title} <span className="sr-only">ready</span></span>
          </li>
        ))}
      </ul>
    </section>
  );
}
