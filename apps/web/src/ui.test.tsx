import { renderToStaticMarkup } from "react-dom/server";
import { describe as group, expect, it } from "vitest";
import { describe } from "./api";
import { challengeFor } from "./auth";
import { Badge, Claim, summarize } from "./Claim";
import { closestSentence } from "./Evidence";
import { formatCost } from "./Cost";
import type { ClaimItem } from "./types";

group("error messages", () => {
  it("prefers the server's detail", () => {
    expect(describe(403, "Access denied to this notebook.")).toBe("Access denied to this notebook.");
  });
  it("explains a missing LLM config", () => {
    expect(describe(503, "No LLM provider configured.")).toMatch(/^The language model is not configured/);
  });
  it("reads FastAPI validation errors", () => {
    expect(describe(422, [{ msg: "String should have at least 1 character" }])).toBe(
      "Invalid input: String should have at least 1 character",
    );
  });
  it("falls back to a generic sentence", () => {
    expect(describe(404, undefined)).toBe("Not found.");
    expect(describe(500, undefined)).toBe("Something went wrong (HTTP 500).");
  });
});

group("claim badges", () => {
  it.each([
    ["verified", "Verified"],
    ["partial", "Partial"],
    ["rejected", "Rejected"],
    ["pending", "Unchecked"],
  ] as const)("%s shows a word, not only a colour", (status, word) => {
    const html = renderToStaticMarkup(<Badge status={status} />);
    expect(html).toContain(`badge-${status}`);
    expect(html).toContain(word);
  });

  it("a rejected claim shows why", () => {
    const claim: ClaimItem = {
      text: "Revenue fell.", citations: [], support_status: "rejected", rejection_reason: "Direction contradicts the quote.",
    };
    const html = renderToStaticMarkup(<Claim claim={claim} selected={false} onSelect={() => {}} />);
    expect(html).toContain("Direction contradicts the quote.");
    expect(html).toContain('aria-pressed="false"');
  });
});

const claim = (support_status: ClaimItem["support_status"]): ClaimItem => ({
  text: "x", citations: [], support_status, rejection_reason: null,
});

group("answer summary", () => {
  it("all verified reads as ok", () => {
    expect(summarize([claim("verified"), claim("verified")])).toEqual({ text: "2 of 2 claims verified", tone: "ok" });
  });
  it("any rejected claim makes the whole answer red", () => {
    expect(summarize([claim("verified"), claim("partial"), claim("rejected")])).toEqual({
      text: "1 of 3 claims verified · 1 partial · 1 rejected", tone: "bad",
    });
  });
  it("partial without rejections is a warning", () => {
    expect(summarize([claim("partial")])?.tone).toBe("warn");
  });
  it("no claims, no summary", () => {
    expect(summarize([])).toBeNull();
  });
});

group("closest sentence", () => {
  const quote = "Apollo 11 landed on July 20, 1969. They collected 47.5 pounds of lunar material. Collins stayed in orbit.";
  it("highlights the sentence sharing most words with the claim, keeping the quote intact", () => {
    const parts = closestSentence(quote, "The crew collected 47.5 pounds of lunar material.");
    expect(parts).toEqual({
      before: "Apollo 11 landed on July 20, 1969. ",
      match: "They collected 47.5 pounds of lunar material. ",
      after: "Collins stayed in orbit.",
    });
    expect(parts && parts.before + parts.match + parts.after).toBe(quote);
  });
  it("does not split decimals or highlight a one-sentence quote", () => {
    expect(closestSentence("It weighed 47.5 pounds.", "47.5 pounds")).toBeNull();
  });
  it("no shared words, no highlight", () => {
    expect(closestSentence(quote, "Zebras graze")).toBeNull();
  });
});

group("cost", () => {
  it("keeps small amounts readable", () => {
    expect(formatCost(0)).toBe("$0");
    expect(formatCost(0.00123)).toBe("$0.0012");
    expect(formatCost(1.5)).toBe("$1.50");
  });
});

group("Cognito sign-in", () => {
  it("derives the PKCE challenge from the verifier (RFC 7636 appendix B)", async () => {
    expect(await challengeFor("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")).toBe(
      "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
    );
  });
});
