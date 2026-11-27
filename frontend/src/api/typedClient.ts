import createClient, { type Middleware } from "openapi-fetch";
import { clearToken, getToken } from "../lib/auth";
import { formatValidationErrors } from "../lib/apiError";
import { plainDetail } from "../lib/setupErrors";
import type { paths } from "./schema.gen";

const DEFAULT_API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

const authMiddleware: Middleware = {
  onRequest({ request }) {
    const token = getToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  onResponse({ response }) {
    if (response.status === 401) clearToken();
    return response;
  },
};

function resolveBaseUrl(baseUrl: string): string {
  if (!/^https?:\/\//i.test(baseUrl) && typeof window !== "undefined" && /^https?:\/\//i.test(window.location?.href ?? "")) {
    return new URL(baseUrl || "/", window.location.href).href.replace(/\/$/, "");
  }
  return baseUrl;
}

export function createTypedClient(baseUrl = DEFAULT_API_BASE) {
  const client = createClient<paths>({ baseUrl: resolveBaseUrl(baseUrl), fetch: (req) => globalThis.fetch(req) });
  client.use(authMiddleware);
  return client;
}

export const typedApi = createTypedClient();

function formatErrorBody(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "detail" in error) {
    const detail = (error as { detail: unknown }).detail;
    if (Array.isArray(detail)) return formatValidationErrors(detail);
    if (typeof detail === "string") return detail || fallback;
    return JSON.stringify(detail ?? error);
  }
  if (typeof error === "string") return error || fallback;
  if (error !== undefined && error !== null) return JSON.stringify(error);
  return fallback;
}

/** Unwrap an openapi-fetch result or throw an Error formatted identically to client.ts. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (!result.response.ok || result.error !== undefined) {
    const detail = formatErrorBody(result.error, result.response.statusText);
    throw new Error(`${result.response.status}: ${plainDetail(detail)}`);
  }
  return result.data as T;
}
