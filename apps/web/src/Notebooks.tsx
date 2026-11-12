import { useState } from "react";
import { api } from "./api";
import { useLoad } from "./hooks";

export function Notebooks() {
  const list = useLoad(api.notebooks, []);
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function create() {
    const t = title.trim();
    if (!t) return;
    setError(null);
    try {
      const nb = await api.createNotebook(t);
      window.location.hash = `#/nb/${nb.id}`;
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <main className="page">
      <h1>Your notebooks</h1>
      <form className="row" onSubmit={(e) => { e.preventDefault(); void create(); }}>
        <label className="sr-only" htmlFor="nbtitle">New notebook title</label>
        <input id="nbtitle" value={title} maxLength={255} placeholder="New notebook title"
               onChange={(e) => setTitle(e.target.value)} />
        <button type="submit" disabled={!title.trim()}>Create</button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {list.loading && <p className="muted">Loading notebooks…</p>}
      {list.error && <p className="error" role="alert">{list.error} <button type="button" className="link" onClick={list.reload}>Retry</button></p>}
      {list.data && list.data.length === 0 && <p className="muted">No notebooks yet. Create one to start.</p>}
      <ul className="cards">
        {list.data?.map((n) => (
          <li key={n.id}><a href={`#/nb/${n.id}`}>{n.title}</a></li>
        ))}
      </ul>
    </main>
  );
}
