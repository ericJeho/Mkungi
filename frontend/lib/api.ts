import { supabase } from "./supabase";

export const API = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** Absolute URL for a path the API returned ("/v1/..." is relative to the API). */
export function apiUrl(pathOrUrl: string): string {
  return pathOrUrl.startsWith("/") ? `${API}${pathOrUrl}` : pathOrUrl;
}

/** The signed-in user's token as a header, or nothing when signed out / sign-in is off. */
export async function authHeader(): Promise<Record<string, string>> {
  if (!supabase) return {};
  const { data } = await supabase.auth.getSession();
  return data.session ? { Authorization: `Bearer ${data.session.access_token}` } : {};
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(apiUrl(path), {
    ...init,
    headers: { ...(await authHeader()), ...(init.headers as Record<string, string> | undefined) },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const message = typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`;
    throw new ApiError(message, res.status);
  }
  return body as T;
}
