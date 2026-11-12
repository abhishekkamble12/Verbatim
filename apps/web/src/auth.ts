// Cognito managed login with the authorization-code + PKCE flow. No SDK: two redirects and one POST.
// Active only when the build has VITE_COGNITO_DOMAIN and VITE_COGNITO_CLIENT_ID (the deploy workflow sets them).
/// <reference types="vite/client" />
const DOMAIN: string | undefined = import.meta.env.VITE_COGNITO_DOMAIN;
const CLIENT_ID: string | undefined = import.meta.env.VITE_COGNITO_CLIENT_ID;
export const cognitoEnabled = Boolean(DOMAIN && CLIENT_ID);

const TOKEN_KEY = "citeguard.token";
const PKCE_KEY = "citeguard.pkce";
const redirectUri = () => `${window.location.origin}/`;

const base64url = (bytes: Uint8Array) =>
  btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const random = (n: number) => base64url(crypto.getRandomValues(new Uint8Array(n)));

/** PKCE S256: the challenge is the SHA-256 of the verifier (RFC 7636). */
export async function challengeFor(verifier: string): Promise<string> {
  return base64url(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier))));
}

// shortcut: no refresh token, so the session ends when the access token does (1 hour) or the tab closes.
// Add the refresh grant if people complain about signing in again.
export const getToken = (): string | null => {
  try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; }
};
export const clearToken = () => {
  try { sessionStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ }
};

export async function signIn(): Promise<void> {
  const verifier = random(32);
  const state = random(16);
  sessionStorage.setItem(PKCE_KEY, JSON.stringify({ verifier, state }));
  const query = new URLSearchParams({
    response_type: "code",
    client_id: CLIENT_ID!,
    redirect_uri: redirectUri(),
    scope: "openid email aws.cognito.signin.user.admin", // the API checks tokens with GetUser, which needs the last one
    code_challenge: await challengeFor(verifier),
    code_challenge_method: "S256",
    state,
  });
  window.location.assign(`https://${DOMAIN}/oauth2/authorize?${query}`);
}

/**
 * Run once on page load. If Cognito sent the browser back with ?code=, swap it for an access token.
 * Returns the signed-in email, or null when this load is not a sign-in return.
 */
export async function completeSignIn(): Promise<string | null> {
  const params = new URLSearchParams(window.location.search);
  const code = params.get("code");
  if (!cognitoEnabled || !code) return null;

  const saved = JSON.parse(sessionStorage.getItem(PKCE_KEY) ?? "null") as { verifier: string; state: string } | null;
  sessionStorage.removeItem(PKCE_KEY);
  window.history.replaceState(null, "", window.location.pathname); // drop the one-time code from the address bar
  // The state must be the one this tab created, or someone else's sign-in is being pushed onto this browser.
  if (!saved || saved.state !== params.get("state")) throw new Error("Sign-in could not be verified. Please try again.");

  const res = await fetch(`https://${DOMAIN}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: CLIENT_ID!,
      code,
      redirect_uri: redirectUri(),
      code_verifier: saved.verifier,
    }),
  });
  if (!res.ok) throw new Error("Sign-in failed. Please try again.");
  const { access_token, id_token } = (await res.json()) as { access_token: string; id_token: string };
  sessionStorage.setItem(TOKEN_KEY, access_token);
  // Only for the name shown in the header; the API identifies the user from the access token.
  const claims = JSON.parse(atob(id_token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))) as { email?: string };
  return claims.email ?? "Signed in";
}

export function signOut(): void {
  clearToken();
  const query = new URLSearchParams({ client_id: CLIENT_ID!, logout_uri: redirectUri() });
  window.location.assign(`https://${DOMAIN}/logout?${query}`);
}
