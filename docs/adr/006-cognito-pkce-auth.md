# ADR-006: AWS Cognito with PKCE over In-House JWT Auth

## Status
Accepted

## Context
User identity and authentication must be secure against token theft, support enterprise standards, and require zero custom cryptographic or password-hashing code in the application codebase.

## Decision
Use Amazon Cognito User Pools with OAuth 2.0 Authorization Code Flow + Proof Key for Code Exchange (PKCE):
- Frontend performs authorization code + PKCE against Cognito's managed login endpoint using native browser Web Crypto API (no AWS Amplify or heavyweight client library dependencies).
- Short-lived Access Tokens are stored in browser `sessionStorage` and sent via `Authorization: Bearer <token>`.
- FastAPI backend validates the token via Cognito `GetUser` or JWKS signature verification.
- Local development provides a clear fallback (`AUTH_MODE=local`) relying on `X-User-Id` headers with explicit configuration refusal when `AUTH_MODE` is unset.

## Consequences
### Positive
- **Zero credential liability**: No passwords, salts, or refresh hashes are stored in the application database.
- **Standards-compliant**: PKCE prevents authorization code interception on public SPA clients.
- **Lightweight client**: Implemented in clean TypeScript using browser standards (`crypto.subtle`) without large SDKs.

### Negative
- Testing against live Cognito requires provisioning a user pool in AWS or running local auth mode.

