import { useEffect, useRef, useState } from "react";
import { api, getUser, setUser } from "./api";
import { cognitoEnabled, signOut as cognitoSignOut } from "./auth";
import { Chat } from "./Chat";
import { Evidence } from "./Evidence";
import { useHash, useLoad } from "./hooks";
import { Notebooks } from "./Notebooks";
import { Report } from "./Report";
import { SignIn } from "./SignIn";
import { Sources } from "./Sources";
import type { ClaimItem } from "./types";

export default function App({ signInError }: { signInError?: string }) {
  const [user, setUserState] = useState(getUser());
  const hash = useHash();

  const signOut = () => {
    setUser(null);
    if (cognitoEnabled) return cognitoSignOut(); // leaves the page to end the Cognito session too
    setUserState(null);
    window.location.hash = "#/";
  };
  if (!user) return <SignIn error={signInError} onSignIn={(id) => { setUser(id); setUserState(id); }} />;

  const nb = /^#\/nb\/([\w-]+)/.exec(hash)?.[1];
  return (
    <>
      <header className="top">
        <a href="#/" className="brand">CiteGuard</a>
        <span className="who">{user} · <button type="button" className="link" onClick={signOut}>Sign out</button></span>
      </header>
      {nb ? <NotebookPage key={`${user}-${nb}`} id={nb} /> : <Notebooks key={user} />}
    </>
  );
}

function NotebookPage({ id }: { id: string }) {
  const [tab, setTab] = useState<"chat" | "report">("chat");
  const [selected, setSelected] = useState<ClaimItem | null>(null);
  const evidence = useRef<HTMLElement>(null);
  const title = useLoad(api.notebooks, []).data?.find((n) => n.id === id)?.title;
  useEffect(() => { if (title) document.title = `${title} · CiteGuard`; }, [title]);

  const select = (c: ClaimItem) => {
    setSelected(c);
    // Stacked layout: the evidence pane is below the chat, so bring it into view.
    if (window.matchMedia("(max-width: 960px)").matches) evidence.current?.scrollIntoView({ behavior: "smooth" });
  };
  return (
    <div className="layout">
      <aside className="pane side"><a href="#/">← All notebooks</a><Sources notebookId={id} /></aside>
      <main className="pane main">
        <h1 className="nb-title">{title ?? " "}</h1>
        <div role="tablist" aria-label="Mode" className="tabs">
          {(["chat", "report"] as const).map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
              {t === "chat" ? "Chat" : "Report"}
            </button>
          ))}
        </div>
        {tab === "chat"
          ? <Chat notebookId={id} selected={selected} onSelect={select} />
          : <Report notebookId={id} selected={selected} onSelect={select} />}
      </main>
      <aside className="pane side" aria-label="Evidence" ref={evidence}>
        <h2>Evidence</h2>
        <Evidence claim={selected} />
      </aside>
    </div>
  );
}
