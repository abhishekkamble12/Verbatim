import { useState } from "react";
import { cognitoEnabled, signIn } from "./auth";

export function SignIn({ onSignIn, error }: { onSignIn: (id: string) => void; error?: string }) {
  const [id, setId] = useState("");
  return (
    <main className="page narrow">
      <h1>CiteGuard</h1>
      <p>Every claim checked against an exact quote, or no answer at all.</p>
      {error && <p className="error" role="alert">{error}</p>}
      {cognitoEnabled ? (
        <button type="button" onClick={() => void signIn()}>Sign in or create an account</button>
      ) : (
        <>
          <form onSubmit={(e) => { e.preventDefault(); if (id.trim()) onSignIn(id.trim()); }}>
            <label htmlFor="uid">Sign in as</label>
            <input id="uid" value={id} onChange={(e) => setId(e.target.value)} placeholder="e.g. alice" autoFocus />
            <button type="submit" disabled={!id.trim()}>Continue</button>
          </form>
          <p className="muted">
            Local development login: the name you type is sent as the user id (the API runs with AUTH_MODE=local).
          </p>
        </>
      )}
    </main>
  );
}
