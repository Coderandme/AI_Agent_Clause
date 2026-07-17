/** The one place this app talks to the backend.
 *
 * Every dynamic action goes through here, and every one of them carries the JWT. The demo does NOT
 * — it is bundled JSON and never touches the network (ROADMAP.md §5.2).
 */

import type { Analysis, TokenResponse, UploadResult, User } from "@/types";

// In dev this points at the local FastAPI; in production it is baked in at build time by Vite.
// Set VITE_API_URL in web/.env.production for the deployed SPA.
const API_URL = import.meta.env["VITE_API_URL"] ?? "http://127.0.0.1:8000";

const TOKEN_KEY = "clause.token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

/** An error carrying the server's own message. The backend writes those messages to be shown to a
 * person verbatim ("You've used your 3 analyses..."), so we surface them rather than inventing our
 * own copy at the call site. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  // Don't set Content-Type for FormData — the browser must add its own multipart boundary.
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch {
    // A network-level failure, not an HTTP error: the API is asleep, down, or CORS-blocked.
    throw new ApiError(
      "Could not reach the server. If you are running locally, is the API started?",
      0,
    );
  }

  if (!res.ok) {
    throw new ApiError(await errorMessage(res), res.status);
  }
  // 204 and friends have no body.
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

/** FastAPI puts the message in `detail`, which is either a string (our HTTPExceptions) or a list of
 * validation errors (Pydantic rejecting the body before the handler ran). Handle both. */
async function errorMessage(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const first = detail[0] as { msg?: string } | undefined;
      if (first?.msg) return first.msg;
    }
  } catch {
    /* not JSON — fall through */
  }
  return `Request failed (${res.status}).`;
}

export const api = {
  signup: (email: string, password: string, access_code: string) =>
    request<TokenResponse>("/api/auth/signup", {
      method: "POST",
      body: JSON.stringify({ email, password, access_code }),
    }),

  login: (email: string, password: string) =>
    request<TokenResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  me: () => request<User>("/api/auth/me"),

  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<UploadResult>("/api/documents", { method: "POST", body: form });
  },

  getAnalysis: (id: string) => request<Analysis>(`/api/analyses/${id}`),
};
