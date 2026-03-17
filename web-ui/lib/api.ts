export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://127.0.0.1:8080";

export const DEFAULT_EXECUTION_MODE =
  process.env.NEXT_PUBLIC_EXECUTION_MODE === "auto" ||
  process.env.NEXT_PUBLIC_EXECUTION_MODE === "distributed"
    ? process.env.NEXT_PUBLIC_EXECUTION_MODE
    : "inline";

export const DEFAULT_RUNTIME_PROFILE =
  process.env.NEXT_PUBLIC_RUNTIME_PROFILE === "balanced" ||
  process.env.NEXT_PUBLIC_RUNTIME_PROFILE === "full"
    ? process.env.NEXT_PUBLIC_RUNTIME_PROFILE
    : "minimal";

export const DEFAULT_QUALITY_PROFILE =
  process.env.NEXT_PUBLIC_QUALITY_PROFILE === "strict" ||
  process.env.NEXT_PUBLIC_QUALITY_PROFILE === "relaxed"
    ? process.env.NEXT_PUBLIC_QUALITY_PROFILE
    : "relaxed";

export const HEALTH_URL = `${API_BASE}/health`;
export const STREAM_BASE_URL = `${API_BASE}/research/stream`;

export function buildStreamUrl(query: string): string {
  return `${STREAM_BASE_URL}?query=${encodeURIComponent(query)}&execution_mode=${DEFAULT_EXECUTION_MODE}&runtime_profile=${DEFAULT_RUNTIME_PROFILE}&quality_profile=${DEFAULT_QUALITY_PROFILE}`;
}

export async function fetchWithTimeout(url: string, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { method: "GET", signal: controller.signal });
  } finally {
    window.clearTimeout(timeout);
  }
}
