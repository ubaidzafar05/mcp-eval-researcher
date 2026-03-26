"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { buildStreamUrl, fetchWithTimeout, HEALTH_URL, ReportLength } from "@/lib/api";
import { BackendHealth, Citation, LogEvent, RunBannerReason, StreamState } from "@/lib/types";

const HEALTH_TIMEOUT_MS = 8000;
const STREAM_FIRST_EVENT_TIMEOUT_MS = 45000;

type StreamPayload = {
  type?: "status" | "token" | "error" | "done" | "final";
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
  reason_codes?: unknown;
  subtopic_total?: number;
  subtopic_completed?: number;
  data?: {
    result?: {
      run_id?: string;
      status?: string;
      final_report?: string;
      citations?: Citation[];
      metrics?: Record<string, unknown>;
      generated_at?: string;
      constrained_reason_codes?: unknown;
    };
  };
};

function withTimestamp(log: Omit<LogEvent, "timestamp">): LogEvent {
  return { ...log, timestamp: new Date().toLocaleTimeString() };
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function normalizeReasonCodes(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((entry) => String(entry));
}

function mergeReasonCodes(prev: string[], next: string[]): string[] {
  if (!next.length) {
    return prev;
  }
  return Array.from(new Set([...prev, ...next]));
}

function bannerFromReasonCodes(codes: string[]): RunBannerReason | null {
  if (codes.includes("dependency_missing_trafilatura")) {
    return "dependency_mismatch";
  }
  if (codes.includes("provider_degraded_ddg_impersonation")) {
    return "provider_degraded";
  }
  if (codes.includes("provider_quota_exhausted")) {
    return "provider_quota";
  }
  return null;
}

function bannerFromMessage(message: string | undefined): RunBannerReason | null {
  if (!message) {
    return null;
  }
  if (message.toLowerCase().includes("quota")) {
    return "provider_quota";
  }
  return null;
}

function shouldMarkHeartbeat(data: StreamPayload): boolean {
  if (data.is_heartbeat) {
    return true;
  }
  const msg = (data.message || "").toLowerCase();
  return msg.includes("still processing sources and synthesis") || msg.includes("still running");
}

function normalizeStageKey(payload: StreamPayload): string {
  const raw = String(payload.active_stage || payload.stage || "").toLowerCase();
  if (
    raw === "starting" ||
    raw === "accepted" ||
    raw === "connecting" ||
    raw === "connected" ||
    raw === "decomposition" ||
    raw === "fallback" ||
    raw === "queued"
  ) {
    return "planning";
  }
  if (raw === "merge" || raw === "self_correction" || raw === "self_correction_retry") {
    return "synthesis";
  }
  if (raw === "eval_gate" || raw === "hitl") {
    return "evaluation";
  }
  if (raw === "finalize") {
    return "finalizing";
  }
  return raw || "planning";
}

function toLogEvent(payload: StreamPayload, type: LogEvent["type"]): Omit<LogEvent, "timestamp"> {
  return {
    type,
    stage: typeof payload.stage === "string" ? payload.stage : undefined,
    active_stage: typeof payload.active_stage === "string" ? payload.active_stage : undefined,
    query: typeof payload.query === "string" ? payload.query : undefined,
    content: typeof payload.content === "string" ? payload.content : undefined,
    message: typeof payload.message === "string" ? payload.message : undefined,
    elapsed_sec: isFiniteNumber(payload.elapsed_sec) ? payload.elapsed_sec : undefined,
    idle_sec: isFiniteNumber(payload.idle_sec) ? payload.idle_sec : undefined,
    idle_threshold_sec: isFiniteNumber(payload.idle_threshold_sec) ? payload.idle_threshold_sec : undefined,
    warned_idle: typeof payload.warned_idle === "boolean" ? payload.warned_idle : undefined,
    is_heartbeat: typeof payload.is_heartbeat === "boolean" ? payload.is_heartbeat : undefined,
    reason_codes: normalizeReasonCodes(payload.reason_codes),
    subtopic_total: isFiniteNumber(payload.subtopic_total) ? payload.subtopic_total : undefined,
    subtopic_completed: isFiniteNumber(payload.subtopic_completed) ? payload.subtopic_completed : undefined,
  };
}

function parseStreamPayload(raw: string): StreamPayload | null {
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object") {
      return null;
    }
    return parsed as StreamPayload;
  } catch {
    return null;
  }
}

export function useResearchRun() {
  const [logs, setLogs] = useState<LogEvent[]>([]);
  const [finalReport, setFinalReport] = useState("");
  const [finalCitations, setFinalCitations] = useState<Citation[]>([]);
  const [finalRunId, setFinalRunId] = useState("");
  const [finalMetrics, setFinalMetrics] = useState<Record<string, unknown>>({});
  const [completedAt, setCompletedAt] = useState<string>("");
  const [isSearching, setIsSearching] = useState(false);
  const [streamState, setStreamState] = useState<StreamState>("idle");
  const [reportNotice, setReportNotice] = useState("Research report will appear here...");
  const [backendHealth, setBackendHealth] = useState<BackendHealth>("unknown");
  const [startupReasonCodes, setStartupReasonCodes] = useState<string[]>([]);
  const [bannerReason, setBannerReason] = useState<RunBannerReason | null>(null);
  const [lastProgressAt, setLastProgressAt] = useState<number | null>(null);
  const [activeStage, setActiveStage] = useState<string>("planning");
  const [nowTick, setNowTick] = useState<number>(Date.now());

  const eventSourceRef = useRef<EventSource | null>(null);
  const finalReceivedRef = useRef(false);
  const firstEventReceivedRef = useRef(false);
  const viewportYRef = useRef(0);
  const activeStageRef = useRef<string>("planning");

  const addLog = useCallback((log: LogEvent) => {
    setLogs((prev) => [...prev, log]);
  }, []);

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  useEffect(() => {
    if (!isSearching) {
      return;
    }
    const timer = window.setInterval(() => {
      setNowTick(Date.now());
    }, 1000);
    return () => window.clearInterval(timer);
  }, [isSearching]);

  const resetRun = useCallback(() => {
    viewportYRef.current = window.scrollY;
    eventSourceRef.current?.close();
    setLogs([]);
    setFinalReport("");
    setFinalCitations([]);
    setFinalRunId("");
    setFinalMetrics({});
    setCompletedAt("");
    setIsSearching(false);
    setStreamState("idle");
    setReportNotice("Research report will appear here...");
    setStartupReasonCodes([]);
    setBannerReason(null);
    setLastProgressAt(null);
    setActiveStage("planning");
    activeStageRef.current = "planning";
    finalReceivedRef.current = false;
    firstEventReceivedRef.current = false;
    requestAnimationFrame(() => window.scrollTo({ top: viewportYRef.current, behavior: "auto" }));
  }, []);

  const stopRun = useCallback(() => {
    eventSourceRef.current?.close();
    setIsSearching(false);
    setStreamState("error");
    setReportNotice("Run was stopped manually before completion.");
    setBannerReason("stream_timeout");
    setActiveStage("finalizing");
    activeStageRef.current = "finalizing";
    addLog(withTimestamp({ type: "error", message: "Run stopped by user." }));
    setLastProgressAt(Date.now());
  }, [addLog]);

  const handleFinalPayload = useCallback((data: StreamPayload) => {
    if (data.stage !== "final" || !data.data?.result?.final_report) {
      return;
    }
    finalReceivedRef.current = true;
    setFinalReport(data.data.result.final_report);
    setFinalCitations(Array.isArray(data.data.result.citations) ? data.data.result.citations : []);
    setFinalRunId(typeof data.data.result.run_id === "string" ? data.data.result.run_id : "");
    setFinalMetrics(
      data.data.result.metrics && typeof data.data.result.metrics === "object"
        ? data.data.result.metrics
        : {},
    );
    setCompletedAt(
      typeof data.data.result.generated_at === "string"
        ? data.data.result.generated_at
        : new Date().toISOString(),
    );
    const finalCodes = normalizeReasonCodes(data.data?.result?.constrained_reason_codes);
    if (finalCodes.length > 0) {
      setStartupReasonCodes((prev) => mergeReasonCodes(prev, finalCodes));
      const banner = bannerFromReasonCodes(finalCodes);
      if (banner) {
        setBannerReason(banner);
      }
    }
    setStreamState("final");
    setActiveStage("final");
    activeStageRef.current = "final";
    setLastProgressAt(Date.now());
    setReportNotice("Final report received.");
  }, []);

  const handleStatusPayload = useCallback(
    (data: StreamPayload) => {
      const isHeartbeat = shouldMarkHeartbeat(data);
      const nextStage = normalizeStageKey(data);
      if (nextStage && nextStage !== activeStageRef.current) {
        activeStageRef.current = nextStage;
        setActiveStage(nextStage);
        setLastProgressAt(Date.now());
      }
      const codes = normalizeReasonCodes(data.reason_codes);
      if (codes.length > 0) {
        setStartupReasonCodes((prev) => mergeReasonCodes(prev, codes));
        const banner = bannerFromReasonCodes(codes);
        if (banner) {
          setBannerReason(banner);
        }
      }
      if (data.stage === "starting" || data.stage === "accepted") {
        setStreamState("connecting");
      } else if (data.stage === "final") {
        setStreamState("final");
      } else {
        setStreamState("running");
      }
      if (data.stage === "fallback") {
        setReportNotice("Distributed mode unavailable, running inline for reliability.");
      }
      const bannerFromMsg = bannerFromMessage(data.message);
      if (bannerFromMsg) {
        setBannerReason(bannerFromMsg);
      }
      if (isHeartbeat && data.warned_idle && String(data.active_stage || data.stage || "").toLowerCase() === "synthesis") {
        setReportNotice("Synthesis is taking longer than usual, but the run is still active.");
      }
      addLog(withTimestamp(toLogEvent(data, "status")));
    },
    [addLog],
  );

  const handleTokenPayload = useCallback(
    (data: StreamPayload) => {
      setStreamState((prev) => (prev === "connecting" ? "running" : prev));
      addLog(withTimestamp(toLogEvent(data, "token")));
    },
    [addLog],
  );

  const handleDonePayload = useCallback(
    (data: StreamPayload, closeStream: () => void) => {
      setLastProgressAt(Date.now());
      setActiveStage("final");
      activeStageRef.current = "final";
      addLog(withTimestamp(toLogEvent(data, "done")));
      closeStream();
      setIsSearching(false);
      if (!finalReceivedRef.current) {
        addLog(
          withTimestamp({
            type: "status",
            stage: "finalizing",
            message: "Run ended without final payload. Retry is recommended.",
          }),
        );
        setStreamState("error");
        setBannerReason("stream_timeout");
        setReportNotice("Run completed without a final report payload. Click Start Deep Research to retry.");
      }
    },
    [addLog],
  );

  const handleErrorPayload = useCallback(
    (data: StreamPayload, closeStream: () => void) => {
      setLastProgressAt(Date.now());
      addLog(withTimestamp(toLogEvent(data, "error")));
      closeStream();
      setIsSearching(false);
      setStreamState("error");
      setActiveStage(normalizeStageKey(data));
      activeStageRef.current = normalizeStageKey(data);
      const banner = bannerFromMessage(data.message) ?? "stream_timeout";
      setBannerReason(banner);
      setReportNotice(data.message || "The stream failed before report completion.");
      setLastProgressAt(Date.now());
    },
    [addLog],
  );

  const initializeRun = useCallback(
    () => {
      viewportYRef.current = window.scrollY;
      eventSourceRef.current?.close();
      setIsSearching(true);
      setLogs([]);
      setFinalReport("");
      setFinalCitations([]);
      setFinalRunId("");
      setFinalMetrics({});
      setCompletedAt("");
      setStreamState("connecting");
      setReportNotice("Connecting to research stream...");
      setStartupReasonCodes([]);
      setBannerReason(null);
      setLastProgressAt(Date.now());
      setActiveStage("planning");
      activeStageRef.current = "planning";
      finalReceivedRef.current = false;
      firstEventReceivedRef.current = false;
      addLog(
        withTimestamp({
          type: "status",
          stage: "connecting",
          message: "Opening stream and preparing execution plan.",
        }),
      );
      requestAnimationFrame(() => window.scrollTo({ top: viewportYRef.current, behavior: "auto" }));
    },
    [addLog],
  );

  const runHealthCheck = useCallback(async (): Promise<string> => {
    let healthIssue = "";
    try {
      const healthResponse = await fetchWithTimeout(HEALTH_URL, HEALTH_TIMEOUT_MS);
      if (healthResponse.ok) {
        setBackendHealth("ok");
        try {
          const healthPayload = await healthResponse.json();
          const reasonCodes = normalizeReasonCodes(healthPayload?.startup_reason_codes);
          if (reasonCodes.length > 0) {
            setStartupReasonCodes(reasonCodes);
            const banner = bannerFromReasonCodes(reasonCodes);
            if (banner) {
              setBannerReason(banner);
            }
          }
        } catch {
          // ignore metadata parse errors
        }
      } else {
        setBackendHealth("down");
        healthIssue = `Health check returned ${healthResponse.status}.`;
      }
    } catch (healthErr) {
      setBackendHealth("down");
      setBannerReason("backend_unavailable");
      healthIssue =
        healthErr instanceof Error && healthErr.name === "AbortError"
          ? `Health check timed out after ${HEALTH_TIMEOUT_MS / 1000}s.`
          : "Health check request failed.";
    }
    return healthIssue;
  }, []);

  const handleStreamOpen = useCallback(() => {
    addLog(withTimestamp({ type: "status", stage: "connected", message: "Stream connection established." }));
  }, [addLog]);

  const handleStreamMessage = useCallback(
    (event: MessageEvent, closeStream: () => void, firstEventTimer: number) => {
      if (!firstEventReceivedRef.current) {
        firstEventReceivedRef.current = true;
        window.clearTimeout(firstEventTimer);
      }

      const payload = parseStreamPayload(event.data);
      if (!payload) {
        addLog(withTimestamp({ type: "error", message: "Stream parse error." }));
        setStreamState("error");
        setReportNotice("Could not parse stream payload. Please retry.");
        return;
      }

      if (payload.type === "token") {
        handleTokenPayload(payload);
      } else if (payload.type === "status") {
        handleStatusPayload(payload);
      } else if (payload.type === "done") {
        handleDonePayload(payload, closeStream);
      } else if (payload.type === "error") {
        handleErrorPayload(payload, closeStream);
      }

      handleFinalPayload(payload);
    },
    [
      addLog,
      handleDonePayload,
      handleErrorPayload,
      handleFinalPayload,
      handleStatusPayload,
      handleTokenPayload,
    ],
  );

  const handleStreamError = useCallback(
    (closeStream: () => void) => {
      addLog(withTimestamp({ type: "error", message: "Stream connection lost." }));
      closeStream();
      setIsSearching(false);
      setLastProgressAt(Date.now());
      setActiveStage("planning");
      activeStageRef.current = "planning";
      if (!finalReceivedRef.current) {
        setStreamState("error");
        setBannerReason("backend_unavailable");
        setReportNotice(
          "Could not maintain stream connection. Restart backend if needed, then click Start Deep Research to retry.",
        );
      }
    },
    [addLog],
  );

  const startFirstEventTimer = useCallback((eventSource: EventSource) => {
    return window.setTimeout(() => {
      if (!firstEventReceivedRef.current && !finalReceivedRef.current) {
        addLog(withTimestamp({ type: "error", message: "No stream events received (startup timeout)." }));
        setIsSearching(false);
        setStreamState("error");
        setBannerReason("stream_timeout");
        setReportNotice("Backend is reachable but stream did not start. Review API logs and retry.");
        setLastProgressAt(Date.now());
        eventSource.close();
      }
    }, STREAM_FIRST_EVENT_TIMEOUT_MS);
  }, [addLog]);

  const openStream = useCallback(
    (query: string, reportLength: ReportLength = "standard") => {
      const streamUrl = buildStreamUrl(query, reportLength);
      const eventSource = new EventSource(streamUrl);
      eventSourceRef.current = eventSource;

      const firstEventTimer = startFirstEventTimer(eventSource);

      const closeStream = () => {
        eventSource.close();
        window.clearTimeout(firstEventTimer);
      };

      eventSource.onopen = handleStreamOpen;
      eventSource.onmessage = (event) => handleStreamMessage(event, closeStream, firstEventTimer);
      eventSource.onerror = () => handleStreamError(closeStream);
    },
    [
      handleStreamError,
      handleStreamMessage,
      handleStreamOpen,
      startFirstEventTimer,
    ],
  );

  const startRun = useCallback(
    async (query: string, reportLength: ReportLength = "standard") => {
      const trimmed = query.trim();
      if (!trimmed) {
        setStreamState("error");
        setReportNotice("Please enter a research question before starting.");
        addLog(withTimestamp({ type: "error", message: "Empty query submitted." }));
        return;
      }

      initializeRun();
      const healthIssue = await runHealthCheck();
      if (healthIssue) {
        addLog(
          withTimestamp({
            type: "status",
            stage: "connecting",
            message: `${healthIssue} Trying stream connection directly...`,
          }),
        );
        setReportNotice("Health check failed, but stream retry is in progress.");
      }
      openStream(trimmed, reportLength);
    },
    [addLog, initializeRun, openStream, runHealthCheck],
  );

  return {
    logs,
    finalReport,
    finalCitations,
    finalRunId,
    finalMetrics,
    completedAt,
    isSearching,
    streamState,
    reportNotice,
    backendHealth,
    startupReasonCodes,
    bannerReason,
    lastProgressAt,
    activeStage,
    nowTick,
    startRun,
    stopRun,
    resetRun,
  };
}
