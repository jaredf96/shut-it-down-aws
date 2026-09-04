/**
 * What a failed request tells the user.
 *
 * The client used to throw away the response body and report
 * "Request failed: 403 Forbidden", which hid the one sentence that answers the
 * question — the backend's own `detail` — and stranded the correlation id that
 * makes the server log findable. These tests pin the four things that has to
 * get right and never regress: the sentence survives, the id is quotable where
 * quoting it helps, a body that is not JSON does not turn into a crash, and
 * nothing that could carry a credential reaches a rendered message.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, createUser, executeCleanup, getHealth, scanAll } from "./client.js";

afterEach(() => {
  vi.restoreAllMocks();
});

/** A Response-alike good enough for the failure path, and no more. */
function errorResponse(status, statusText, bodyText, headers = {}) {
  return {
    ok: false,
    status,
    statusText,
    headers: new Headers(headers),
    text: async () => bodyText,
  };
}

function stub(response) {
  global.fetch = vi.fn(async () => response);
}

/** Reject-or-fail-loudly: a call that resolves must not pass silently. */
async function rejection(promise) {
  return promise.then(
    () => {
      throw new Error("expected a rejection");
    },
    (e) => e
  );
}

describe("the backend's own words", () => {
  it("surfaces the detail as the message", async () => {
    stub(
      errorResponse(403, "Forbidden", JSON.stringify({ detail: "Cleanup actions are disabled in this environment." }), {
        "X-Correlation-ID": "abc123def456",
      })
    );

    const err = await rejection(
      executeCleanup({ action: "stop_ec2_instance", resource_id: "i-1", confirm_resource_id: "i-1" })
    );

    expect(err.name).toBe("ApiError");
    expect(err.message).toBe("Cleanup actions are disabled in this environment.");
    expect(err.detail).toBe("Cleanup actions are disabled in this environment.");
    expect(err.status).toBe(403);
    expect(err.correlationId).toBe("abc123def456");
    // A refusal explains itself; a reference number on it would be noise.
    expect(err.message).not.toContain("ref");
  });

  it("flattens a 422 validation detail into a sentence", async () => {
    stub(
      errorResponse(
        422,
        "Unprocessable Entity",
        JSON.stringify({
          detail: [{ loc: ["body", "confirm_resource_id"], msg: "Field required", type: "missing" }],
        })
      )
    );

    const err = await rejection(executeCleanup({}));

    // Neither a crash nor "[object Object]" — the shape FastAPI actually sends.
    expect(err.message).toBe("Field required.");
    expect(err.detail).toBe("Field required");
  });
});

describe("the correlation id", () => {
  it("is quoted on a server fault, header first", async () => {
    stub(
      errorResponse(
        500,
        "Internal Server Error",
        JSON.stringify({ detail: "Internal server error.", error: "internal_error", correlation_id: "bodyid" }),
        { "X-Correlation-ID": "headerid" }
      )
    );

    const err = await rejection(getHealth());

    expect(err.message).toBe("Internal server error. (ref headerid)");
    expect(err.code).toBe("internal_error");
    expect(err.status).toBe(500);
  });

  it("falls back to the body when the response carries no headers at all", async () => {
    // A 503 envelope, and a stub with no `headers` — the `res.headers?.get?.()`
    // guard is what keeps this from throwing instead of reporting.
    global.fetch = vi.fn(async () => ({
      ok: false,
      status: 503,
      statusText: "Service Unavailable",
      text: async () =>
        JSON.stringify({
          detail: "Persistence is required for scan history.",
          error: "persistence_unavailable",
          correlation_id: "bodyid",
        }),
    }));

    const err = await rejection(getHealth());

    expect(err.correlationId).toBe("bodyid");
    expect(err.message).toBe("Persistence is required for scan history. (ref bodyid)");
  });
});

describe("bodies that are not an envelope", () => {
  it("survives a proxy's HTML", async () => {
    stub(errorResponse(502, "Bad Gateway", "<html><body><h1>502 Bad Gateway</h1></body></html>"));

    const err = await rejection(scanAll());

    expect(err.name).toBe("ApiError"); // not a SyntaxError from JSON.parse
    expect(err.message).toBe("Request failed: 502 Bad Gateway.");
    expect(err.detail).toBeNull();
    expect(err.body).toContain("502 Bad Gateway"); // kept for the console
    expect(err.message).not.toContain("<html"); // never spliced into the banner
  });

  it.each([
    ["an empty body", errorResponse(503, "Service Unavailable", ""), "Request failed: 503 Service Unavailable."],
    ["no statusText (HTTP/2)", errorResponse(502, "", ""), "Request failed: 502."],
  ])("reads as something with %s", async (_label, response, expected) => {
    stub(response);
    const err = await rejection(scanAll());
    expect(err.message).toBe(expected);
  });

  it("survives a stream that dies mid-body", async () => {
    global.fetch = vi.fn(async () => ({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      headers: new Headers(),
      text: async () => {
        throw new TypeError("network error");
      },
    }));

    const err = await rejection(scanAll());

    expect(err.name).toBe("ApiError");
    expect(err.status).toBe(500);
  });
});

describe("no response at all", () => {
  it.each([
    ["a read", () => scanAll()],
    ["a write", () => createUser({ name: "x" })],
  ])("rejects with a sentence when %s cannot reach the API", async (_label, call) => {
    global.fetch = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });

    const err = await rejection(call());

    expect(err.name).toBe("ApiError");
    expect(err.message).toBe("Could not reach the API.");
    expect(err.status).toBeNull();
    expect(err.code).toBe("network_error");
    expect(err.message).toMatch(/[.!?)]$/);
    expect(err.message).not.toContain("localhost");
  });
});

describe("what never reaches a rendered message", () => {
  it.each([
    ["an auth refusal", errorResponse(401, "Unauthorized", JSON.stringify({ detail: "Invalid API key." }))],
    ["a proxy's HTML", errorResponse(502, "Bad Gateway", "<html>localhost:8000 upstream failed</html>")],
  ])("keeps the base URL and credentials out of %s", async (_label, response) => {
    stub(response);

    const err = await rejection(scanAll());

    // BASE_URL defaults to http://localhost:8000, so "localhost" is a canary.
    expect(err.message).not.toContain("localhost");
    expect(err.message).not.toContain("X-API-Key");
    // `body` is the deliberate exception — raw response text, kept for the
    // console and never rendered. Every other field has to be safe to display.
    const { body, ...displayable } = err;
    expect(JSON.stringify({ ...displayable, message: err.message })).not.toContain("localhost");
  });
});

describe("the success path", () => {
  it("is left alone", async () => {
    const text = vi.fn();
    global.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ ok: 1 }), text }));

    await expect(getHealth()).resolves.toEqual({ ok: 1 });
    expect(text).not.toHaveBeenCalled();
  });
});

describe("ApiError", () => {
  it("is constructible with nothing but a message", () => {
    const err = new ApiError("Something went wrong.");
    expect(err).toBeInstanceOf(Error);
    expect(err.status).toBeNull();
    expect(err.detail).toBeNull();
    expect(err.correlationId).toBeNull();
  });
});
