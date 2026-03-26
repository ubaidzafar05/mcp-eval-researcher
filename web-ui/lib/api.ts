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

export type ReportLength = "brief" | "standard" | "comprehensive" | "deep";

export const REPORT_LENGTH_OPTIONS: {
  value: ReportLength;
  label: string;
  words: string;
  eta: string;
}[] = [
  { value: "brief", label: "Brief", words: "~1,500 words", eta: "~3 min" },
  { value: "standard", label: "Standard", words: "~3,000 words", eta: "~6 min" },
  { value: "comprehensive", label: "Comprehensive", words: "~5,000 words", eta: "~12 min" },
  { value: "deep", label: "Deep Dive", words: "~8,000 words", eta: "~20 min" },
];

export const HEALTH_URL = `${API_BASE}/health/live`;
export const STREAM_BASE_URL = `${API_BASE}/research/stream`;
export const EXPORT_PDF_URL = `${API_BASE}/api/v1/export-pdf`;

export function buildStreamUrl(query: string, reportLength: ReportLength = "standard"): string {
  return `${STREAM_BASE_URL}?query=${encodeURIComponent(query)}&execution_mode=${DEFAULT_EXECUTION_MODE}&runtime_profile=${DEFAULT_RUNTIME_PROFILE}&quality_profile=${DEFAULT_QUALITY_PROFILE}&report_length=${reportLength}`;
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

export async function exportReportPdf(payload: {
  runId: string;
  report: string;
  citations: unknown[];
}): Promise<Blob> {
  const response = await fetch(EXPORT_PDF_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      run_id: payload.runId,
      report: payload.report,
      citations: payload.citations,
    }),
  });
  if (!response.ok) {
    throw new Error(`PDF export failed with ${response.status}`);
  }
  return response.blob();
}
