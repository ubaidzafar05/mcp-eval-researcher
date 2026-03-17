export type StreamState = "idle" | "connecting" | "running" | "final" | "error";
export type BackendHealth = "unknown" | "ok" | "down";
export type RunBannerReason =
  | "dependency_mismatch"
  | "provider_quota"
  | "provider_degraded"
  | "stream_timeout"
  | "backend_unavailable";

export interface LogEvent {
  type: "status" | "token" | "error" | "done";
  stage?: string;
  active_stage?: string;
  query?: string;
  content?: string;
  message?: string;
  elapsed_sec?: number;
  idle_sec?: number;
  idle_threshold_sec?: number;
  warned_idle?: boolean;
  is_heartbeat?: boolean;
  reason_codes?: string[];
  subtopic_total?: number;
  subtopic_completed?: number;
  timestamp: string;
}
