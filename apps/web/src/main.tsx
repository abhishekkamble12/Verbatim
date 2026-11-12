import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { setUser } from "./api";
import App from "./App";
import { completeSignIn } from "./auth";
import "./styles.css";

// Finish a Cognito sign-in (if this load is the redirect back) before the first render decides who is signed in.
completeSignIn()
  .then((email) => { if (email) setUser(email); return undefined; }, (e: Error) => e.message)
  .then((signInError) => {
    createRoot(document.getElementById("root")!).render(<StrictMode><App signInError={signInError} /></StrictMode>);
  });
