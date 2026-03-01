"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  BookText,
  ChevronDown,
  ChevronUp,
  CircleStop,
  RefreshCw,
  Wifi,
  WifiOff,
} from "lucide-react";

import { LiveStream, LogEvent } from "@/components/LiveStream";
import { ReportView } from "@/components/ReportView";
import { ResearchForm } from "@/components/ResearchForm";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { MetricChip } from "@/components/ui/metric-chip";
import { ThemeMode, ThemeToggle } from "@/components/ui/theme-toggle";
import { WorkspacePane } from "@/components/ui/workspace-pane";

type StreamState = "idle" | "connecting" | "running" | "final" | "error";
type BackendHealth = "unknown" | "ok" | "down";
type ThemeResolved = "light" | "dark";
type RunBannerReason =
  | "dependency_mismatch"
  | "provider_quota"
  | "provider_degraded"
  | "stream_timeout"
  | "backend_unavailable";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://127.0.0.1:8080";
const HEALTH_TIMEOUT_MS = 8000;
const STREAM_FIRST_EVENT_TIMEOUT_MS = 15000;
const DEFAULT_EXECUTION_MODE =
  process.env.NEXT_PUBLIC_EXECUTION_MODE === "auto" ||
  process.env.NEXT_PUBLIC_EXECUTION_MODE === "distributed"
    ? process.env.NEXT_PUBLIC_EXECUTION_MODE
    : "inline";
const DEFAULT_RUNTIME_PROFILE =
  process.env.NEXT_PUBLIC_RUNTIME_PROFILE === "balanced" ||
  process.env.NEXT_PUBLIC_RUNTIME_PROFILE === "full"
    ? process.env.NEXT_PUBLIC_RUNTIME_PROFILE
    : "minimal";
const DEFAULT_THEME_MODE: ThemeMode =
  process.env.NEXT_PUBLIC_DEFAULT_THEME === "light" || process.env.NEXT_PUBLIC_DEFAULT_THEME === "dark"
    ? process.env.NEXT_PUBLIC_DEFAULT_THEME
    : "system";
const THEME_STORAGE_KEY = "cloudhive.theme_mode";
const UI_VERSION = (process.env.NEXT_PUBLIC_UI_VERSION || "v6").toLowerCase();
const USE_V6_UI = UI_VERSION === "v6";

const healthUrl = `${API_BASE}/health`;
const streamBaseUrl = `${API_BASE}/research/stream`;

function parseThemeMode(value: string | null): ThemeMode | null {
  if (value === "system" || value === "light" || value === "dark") {
    return value;
  }
  return null;
}

function resolveTheme(themeMode: ThemeMode): ThemeResolved {
  if (themeMode === "system") {
    if (typeof window === "undefined") {
      return "light";
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return themeMode;
}

const STATUS_META: Record<
  StreamState,
  {
    label: string;
    detail: string;
    tone: "neutral" | "teal" | "amber" | "error";
    barClass: string;
  }
> = {
  idle: {
    label: "Idle",
    detail: "System is ready for a new research run.",
    tone: "neutral",
    barClass: "topbar-status topbar-status--idle",
  },
  connecting: {
    label: "Connecting",
    detail: "Establishing stream and initializing the pipeline.",
    tone: "amber",
    barClass: "topbar-status topbar-status--connecting",
  },
  running: {
    label: "Running",
    detail: "Research is collecting evidence and synthesizing output.",
    tone: "teal",
    barClass: "topbar-status topbar-status--running",
  },
  final: {
    label: "Finalized",
    detail: "Final report payload received and rendered.",
    tone: "teal",
    barClass: "topbar-status topbar-status--final",
  },
  error: {
    label: "Needs attention",
    detail: "Run ended unexpectedly. Review monitor details and retry.",
    tone: "error",
    barClass: "topbar-status topbar-status--error",
  },
};

export default function Home() {
  const [logs, setLogs] = useState<LogEvent[]>([]);
  const [finalReport, setFinalReport] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [streamState, setStreamState] = useState<StreamState>("idle");
  const [reportNotice, setReportNotice] = useState("Research report will appear here...");
  const [backendHealth, setBackendHealth] = useState<BackendHealth>("unknown");
  const [startupReasonCodes, setStartupReasonCodes] = useState<string[]>([]);
  const [bannerReason, setBannerReason] = useState<RunBannerReason | null>(null);
  const [intelOpen, setIntelOpen] = useState(false);
  const [lastProgressAt, setLastProgressAt] = useState<number | null>(null);
  const [nowTick, setNowTick] = useState<number>(Date.now());
  const [themeMode, setThemeMode] = useState<ThemeMode>(DEFAULT_THEME_MODE);
  const [resolvedTheme, setResolvedTheme] = useState<ThemeResolved>(
    DEFAULT_THEME_MODE === "dark" ? "dark" : "light",
  );

  const eventSourceRef = useRef<EventSource | null>(null);
  const finalReceivedRef = useRef(false);
  const firstEventReceivedRef = useRef(false);
  const viewportYRef = useRef(0);
  const themeBootstrappedRef = useRef(false);

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  useLayoutEffect(() => {
    if (!themeBootstrappedRef.current) {
      themeBootstrappedRef.current = true;
      const stored = parseThemeMode(window.localStorage.getItem(THEME_STORAGE_KEY));
      if (stored && stored !== themeMode) {
        setThemeMode(stored);
        return;
      }
    }
    const resolved = resolveTheme(themeMode);
    setResolvedTheme(resolved);
    document.documentElement.dataset.theme = resolved;
    window.localStorage.setItem(THEME_STORAGE_KEY, themeMode);
  }, [themeMode]);

  useEffect(() => {
    if (themeMode !== "system") {
      return;
    }
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = () => {
      const nextResolved = media.matches ? "dark" : "light";
      setResolvedTheme(nextResolved);
      document.documentElement.dataset.theme = nextResolved;
    };
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", handleChange);
      return () => media.removeEventListener("change", handleChange);
    }
    media.addListener(handleChange);
    return () => media.removeListener(handleChange);
  }, [themeMode]);

  useEffect(() => {
    if (!isSearching) {
      return;
    }
    const timer = window.setInterval(() => {
      setNowTick(Date.now());
    }, 1000);
    return () => window.clearInterval(timer);
  }, [isSearching]);

  useEffect(() => {
    if (streamState === "connecting" || streamState === "running" || streamState === "error") {
      setIntelOpen(true);
      return;
    }
    if (streamState === "final" && finalReport) {
      setIntelOpen(false);
    }
  }, [finalReport, streamState]);

  const addLog = (log: LogEvent) => {
    setLogs((prev) => [...prev, log]);
  };

  const withTimestamp = (log: Omit<LogEvent, "timestamp">): LogEvent => ({
    ...log,
    timestamp: new Date().toLocaleTimeString(),
  });

  const fetchWithTimeout = async (url: string, timeoutMs: number): Promise<Response> => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(url, { method: "GET", signal: controller.signal });
    } finally {
      window.clearTimeout(timeout);
    }
  };

  const resetWorkspace = () => {
    viewportYRef.current = window.scrollY;
    eventSourceRef.current?.close();
    setLogs([]);
    setFinalReport("");
    setIsSearching(false);
    setStreamState("idle");
    setReportNotice("Research report will appear here...");
    setStartupReasonCodes([]);
    setBannerReason(null);
    setIntelOpen(false);
    setLastProgressAt(null);
    finalReceivedRef.current = false;
    firstEventReceivedRef.current = false;
    requestAnimationFrame(() => window.scrollTo({ top: viewportYRef.current, behavior: "auto" }));
  };

  const stopRun = () => {
    eventSourceRef.current?.close();
    setIsSearching(false);
    setStreamState("error");
    setReportNotice("Run was stopped manually before completion.");
    setBannerReason("stream_timeout");
    addLog(withTimestamp({ type: "error", message: "Run stopped by user." }));
    setLastProgressAt(Date.now());
  };

  const handleSearch = async (query: string) => {
    const trimmed = query.trim();
    if (!trimmed) {
      setStreamState("error");
      setReportNotice("Please enter a research question before starting.");
      addLog(withTimestamp({ type: "error", message: "Empty query submitted." }));
      return;
    }

    viewportYRef.current = window.scrollY;
    eventSourceRef.current?.close();

    setIsSearching(true);
    setLogs([]);
    setFinalReport("");
    setStreamState("connecting");
    setReportNotice("Connecting to research stream...");
    setStartupReasonCodes([]);
    setBannerReason(null);
    setLastProgressAt(Date.now());
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

    try {
      let healthIssue = "";
      try {
        const healthResponse = await fetchWithTimeout(healthUrl, HEALTH_TIMEOUT_MS);
        if (healthResponse.ok) {
          setBackendHealth("ok");
          try {
            const healthPayload = await healthResponse.json();
            const reasonCodes = Array.isArray(healthPayload?.startup_reason_codes)
              ? (healthPayload.startup_reason_codes as string[])
              : [];
            if (reasonCodes.length > 0) {
              setStartupReasonCodes(reasonCodes);
              if (reasonCodes.includes("dependency_missing_trafilatura")) {
                setBannerReason("dependency_mismatch");
              }
            }
          } catch {
            // ignore parse errors on health metadata; status code is enough for connectivity.
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

      const streamUrl = `${streamBaseUrl}?query=${encodeURIComponent(trimmed)}&execution_mode=${DEFAULT_EXECUTION_MODE}&runtime_profile=${DEFAULT_RUNTIME_PROFILE}`;
      const eventSource = new EventSource(streamUrl);
      eventSourceRef.current = eventSource;

      const firstEventTimer = window.setTimeout(() => {
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

      eventSource.onopen = () => {
        addLog(withTimestamp({ type: "status", stage: "connected", message: "Stream connection established." }));
      };

      eventSource.onmessage = (event) => {
        try {
          if (!firstEventReceivedRef.current) {
            firstEventReceivedRef.current = true;
            window.clearTimeout(firstEventTimer);
          }

          const data = JSON.parse(event.data);

          if (data.type === "token") {
            setLastProgressAt(Date.now());
            setStreamState((prev) => (prev === "connecting" ? "running" : prev));
            addLog(withTimestamp({ ...data, type: "token" }));
          } else if (data.type === "status") {
            const isHeartbeat = Boolean(data.is_heartbeat);
            if (!isHeartbeat) {
              setLastProgressAt(Date.now());
            }
            if (Array.isArray(data.reason_codes) && data.reason_codes.length > 0) {
              const codes = (data.reason_codes as unknown[]).map((entry) => String(entry));
              setStartupReasonCodes(codes);
              if (codes.includes("dependency_missing_trafilatura")) {
                setBannerReason("dependency_mismatch");
              }
              if (codes.includes("provider_degraded_ddg_impersonation")) {
                setBannerReason("provider_degraded");
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
            if ((data.message || "").toLowerCase().includes("quota")) {
              setBannerReason("provider_quota");
            }
            if (
              isHeartbeat &&
              data.warned_idle &&
              String(data.active_stage || data.stage || "").toLowerCase() === "synthesis"
            ) {
              setReportNotice("Synthesis is taking longer than usual, but the run is still active.");
            }
            addLog(withTimestamp({ ...data, type: "status" }));
          } else if (data.type === "done") {
            setLastProgressAt(Date.now());
            addLog(withTimestamp({ ...data, type: "done" }));
            eventSource.close();
            window.clearTimeout(firstEventTimer);
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
              setReportNotice(
                "Run completed without a final report payload. Click Start Deep Research to retry.",
              );
            }
          } else if (data.type === "error") {
            setLastProgressAt(Date.now());
            addLog(withTimestamp({ ...data, type: "error" }));
            eventSource.close();
            window.clearTimeout(firstEventTimer);
            setIsSearching(false);
            setStreamState("error");
            if ((data.message || "").toLowerCase().includes("quota")) {
              setBannerReason("provider_quota");
            } else {
              setBannerReason("stream_timeout");
            }
            setReportNotice(data.message || "The stream failed before report completion.");
            setLastProgressAt(Date.now());
          }

          if (data.stage === "final" && data.data?.result?.final_report) {
            finalReceivedRef.current = true;
            setFinalReport(data.data.result.final_report);
            const finalReasonCodes = Array.isArray(data.data?.result?.constrained_reason_codes)
              ? (data.data.result.constrained_reason_codes as unknown[]).map((entry) => String(entry))
              : [];
            if (finalReasonCodes.length > 0) {
              setStartupReasonCodes((prev) => Array.from(new Set([...prev, ...finalReasonCodes])));
              if (finalReasonCodes.includes("provider_quota_exhausted")) {
                setBannerReason("provider_quota");
              }
            }
            setStreamState("final");
            setReportNotice("Final report received.");
          }
        } catch {
          addLog(withTimestamp({ type: "error", message: "Stream parse error." }));
          setStreamState("error");
          setReportNotice("Could not parse stream payload. Please retry.");
        }
      };

      eventSource.onerror = () => {
          addLog(withTimestamp({ type: "error", message: "Stream connection lost." }));
        eventSource.close();
        window.clearTimeout(firstEventTimer);
        setIsSearching(false);
        setLastProgressAt(Date.now());
        if (!finalReceivedRef.current) {
          setStreamState("error");
          setBannerReason("backend_unavailable");
          setReportNotice(
            "Could not maintain stream connection. Restart backend if needed, then click Start Deep Research to retry.",
          );
        }
      };
    } catch (error) {
      const detail =
        error instanceof Error && error.name === "AbortError"
          ? `Health check timed out after ${HEALTH_TIMEOUT_MS / 1000}s.`
          : "Failed to start stream.";
      addLog(withTimestamp({ type: "error", message: detail }));
      setBackendHealth("down");
      setIsSearching(false);
      setStreamState("error");
      setBannerReason("backend_unavailable");
      setReportNotice("Unable to start stream connection. Start/restart backend services and retry.");
      setLastProgressAt(Date.now());
    }
  };

  const status = STATUS_META[streamState];
  const shouldShowLiveTimer =
    isSearching && (streamState === "connecting" || streamState === "running") && lastProgressAt !== null;
  const lastUpdateSeconds =
    lastProgressAt !== null ? Math.max(0, Math.floor((nowTick - lastProgressAt) / 1000)) : 0;

  const emptyReportText =
    streamState === "error"
      ? reportNotice
      : streamState === "final"
        ? "Run finalized, but no report body was returned."
        : "Report content appears here once synthesis and quality gates complete.";

  const healthLabel = useMemo(() => {
    if (backendHealth === "ok") return "Connected";
    if (backendHealth === "down") return "Unavailable";
    return "Unknown";
  }, [backendHealth]);
  const branchProgress = useMemo(() => {
    let total = 0;
    let completed = 0;
    for (const log of logs) {
      const nextTotal = Number(log.subtopic_total ?? 0);
      const nextCompleted = Number(log.subtopic_completed ?? 0);
      if (Number.isFinite(nextTotal) && nextTotal > total) {
        total = nextTotal;
      }
      if (Number.isFinite(nextCompleted) && nextCompleted > completed) {
        completed = nextCompleted;
      }
    }
    return { total, completed: Math.min(completed, total || completed) };
  }, [logs]);

  const providerBanner = useMemo(() => {
    const quotaSignalInLogs = logs.some((log) =>
      (log.message || "").toLowerCase().includes("quota"),
    );
    const constrainedSignalInReport =
      finalReport.toLowerCase().includes("constrained-actionable mode") ||
      finalReport.toLowerCase().includes("provider constraints") ||
      finalReport.toLowerCase().includes("provider_quota_exhausted");
    const providerWarning = quotaSignalInLogs || constrainedSignalInReport;
    if (!providerWarning) {
      return null;
    }
    return {
      tone: "amber" as const,
      title: "Provider capacity constraint",
      message:
        "Some providers were limited for this run. Report is constrained; retry after quota reset or with upgraded provider capacity.",
      action: "Action: rerun later or switch to a key with available credits.",
    };
  }, [finalReport, logs]);

  const errorBanner = useMemo(() => {
    if (streamState !== "error") {
      return null;
    }
    return {
      tone: "error" as const,
      title: "Run needs attention",
      message: reportNotice,
      action: "Action: check backend health, then click Start Deep Research to retry.",
    };
  }, [reportNotice, streamState]);

  const effectiveBannerReason = useMemo<RunBannerReason | null>(() => {
    if (bannerReason) {
      return bannerReason;
    }
    if (startupReasonCodes.includes("dependency_missing_trafilatura")) {
      return "dependency_mismatch";
    }
    const reportLower = finalReport.toLowerCase();
    const logHasQuotaSignal = logs.some((log) => (log.message || "").toLowerCase().includes("quota"));
    const logHasDdgDegradedSignal = logs.some((log) => {
      const message = (log.message || "").toLowerCase();
      return (
        message.includes("provider_degraded_ddg_impersonation") ||
        (Array.isArray(log.reason_codes) &&
          log.reason_codes.some((code) => String(code).includes("provider_degraded_ddg_impersonation")))
      );
    });
    if (
      logHasQuotaSignal ||
      reportLower.includes("provider_quota_exhausted") ||
      reportLower.includes("provider constraints")
    ) {
      return "provider_quota";
    }
    if (logHasDdgDegradedSignal || reportLower.includes("provider_degraded_ddg_impersonation")) {
      return "provider_degraded";
    }
    if (streamState === "error" && backendHealth === "down") {
      return "backend_unavailable";
    }
    if (streamState === "error") {
      return "stream_timeout";
    }
    return null;
  }, [backendHealth, bannerReason, finalReport, logs, startupReasonCodes, streamState]);

  const bannerConfig = useMemo(() => {
    if (effectiveBannerReason === "dependency_mismatch") {
      return {
        tone: "warn" as const,
        title: "Dependency fallback active",
        message:
          "Backend started in reduced extraction mode because optional parser dependencies are missing in the active Python environment.",
        action: "Action: run backend with Poetry env (`poetry run uvicorn service.api:app --host 127.0.0.1 --port 8080`).",
      };
    }
    if (effectiveBannerReason === "provider_quota") {
      return {
        tone: "warn" as const,
        title: "Provider capacity limited",
        message:
          "One or more research providers hit quota/plan limits. Report quality is constrained until provider capacity recovers.",
        action: "Action: retry after quota reset or use a key with available credits.",
      };
    }
    if (effectiveBannerReason === "provider_degraded") {
      return {
        tone: "warn" as const,
        title: "Provider degraded",
        message:
          "DuckDuckGo text retrieval degraded in this run and auto-shifted to alternate providers.",
        action: "Action: continue with current report or rerun after DDG client/runtime update.",
      };
    }
    if (effectiveBannerReason === "backend_unavailable") {
      return {
        tone: "error" as const,
        title: "Backend unavailable",
        message: "Stream transport could not reach a healthy backend endpoint for this run.",
        action: "Action: restart backend, confirm /health, then run again.",
      };
    }
    if (effectiveBannerReason === "stream_timeout") {
      return {
        tone: "error" as const,
        title: "Stream startup timed out",
        message: "The request started but no pipeline stream events were received within the startup window.",
        action: "Action: inspect API logs and retry once backend health is stable.",
      };
    }
    return null;
  }, [effectiveBannerReason]);

  if (USE_V6_UI) {
    return (
      <main className="nova-root" data-run-state={streamState}>
        <div className="nova-shell">
          <header className="nova-topbar panel-enter">
            <div className="nova-brand">
              <p className="nova-brand__eyebrow">Cloud Hive Research OS</p>
              <h1 className="nova-brand__title">Editorial Control Room</h1>
            </div>
            <div className="nova-topbar__right">
              <ThemeToggle value={themeMode} onChange={setThemeMode} />
              <MetricChip tone={backendHealth === "down" ? "error" : "teal"}>
                {backendHealth === "down" ? <WifiOff className="h-3.5 w-3.5" /> : <Wifi className="h-3.5 w-3.5" />}
                API {healthLabel}
              </MetricChip>
              <MetricChip tone="neutral">{status.label}</MetricChip>
              <MetricChip tone="neutral">{DEFAULT_EXECUTION_MODE}</MetricChip>
              <Button type="button" size="sm" variant="outline" onClick={resetWorkspace} disabled={isSearching}>
                <RefreshCw className="h-3.5 w-3.5" /> Reset
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={stopRun} disabled={!isSearching}>
                <CircleStop className="h-3.5 w-3.5" /> Stop
              </Button>
            </div>
          </header>

          {bannerConfig ? (
            <section className={`nova-banner panel-enter ${bannerConfig.tone === "error" ? "nova-banner--error" : "nova-banner--warn"}`}>
              <p className="nova-banner__title">{bannerConfig.title}</p>
              <p className="nova-banner__message">{bannerConfig.message}</p>
              <p className="nova-banner__action">{bannerConfig.action}</p>
            </section>
          ) : null}

          <section className="nova-layout">
            <aside className="nova-command panel-enter">
              <div className="nova-command__head">
                <h2>Command Rail</h2>
                <MetricChip tone={status.tone}>{status.label}</MetricChip>
              </div>
              <p className="nova-command__subhead">Drive the run from here, then read results in the main canvas.</p>
              <ResearchForm onSearch={handleSearch} isSearching={isSearching} />
              <div className="nova-command__foot">
                <p>{status.detail}</p>
                {shouldShowLiveTimer ? (
                  <p className="nova-command__live">Last progress {lastUpdateSeconds}s ago.</p>
                ) : null}
              </div>
            </aside>

            <section className="nova-main panel-enter">
              <header className="nova-main__head">
                <div>
                  <p className="nova-main__eyebrow">Answer Brief</p>
                  <h2 className="nova-main__title">
                    <BookText className="h-4 w-4" /> Research Narrative
                  </h2>
                </div>
                <div className="nova-main__chips">
                  <MetricChip tone={finalReport ? "teal" : "neutral"}>
                    {finalReport ? "Report ready" : "Awaiting report"}
                  </MetricChip>
                  <MetricChip tone="neutral">{logs.length} events</MetricChip>
                  {branchProgress.total > 0 ? (
                    <MetricChip tone="neutral">
                      Branches {branchProgress.completed}/{branchProgress.total}
                    </MetricChip>
                  ) : null}
                  <MetricChip tone="neutral">Profile {DEFAULT_RUNTIME_PROFILE}</MetricChip>
                </div>
              </header>

              <div className="nova-main__body">
                {finalReport ? (
                  <ReportView report={finalReport} />
                ) : (
                  <Card className="reader-placeholder">
                    <CardHeader className="border-b border-border/70 pb-4">
                      <CardTitle className="text-base font-semibold">Research Report</CardTitle>
                      <CardDescription className="text-sm text-muted-foreground">{reportNotice}</CardDescription>
                    </CardHeader>
                    <CardContent className="pt-6">
                      {isSearching ? (
                        <div className="space-y-3">
                          <div className="skeleton-line h-4 w-11/12" />
                          <div className="skeleton-line h-4 w-9/12" />
                          <div className="skeleton-line h-4 w-10/12" />
                          <div className="skeleton-line h-4 w-8/12" />
                        </div>
                      ) : (
                        <div className="reader-placeholder__empty">
                          {streamState === "error" ? <AlertTriangle className="h-4 w-4" /> : null}
                          <span>{emptyReportText}</span>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                )}
              </div>
            </section>
          </section>

          <section className={`nova-dock panel-enter ${intelOpen ? "nova-dock--open" : "nova-dock--closed"}`}>
            <button
              type="button"
              className="nova-dock__toggle"
              onClick={() => setIntelOpen((prev) => !prev)}
              aria-expanded={intelOpen}
            >
              <div className="nova-dock__toggle-main">
                <span className="nova-dock__toggle-text">Pipeline Monitor</span>
                <span className="nova-dock__toggle-meta">
                  {intelOpen ? "Collapse" : "Expand"} live execution
                </span>
              </div>
              <div className="nova-dock__toggle-pills" aria-hidden="true">
                <MetricChip tone="neutral">{logs.length} events</MetricChip>
                {branchProgress.total > 0 ? (
                  <MetricChip tone="neutral">
                    {branchProgress.completed}/{branchProgress.total} branches
                  </MetricChip>
                ) : null}
                <MetricChip tone="neutral">{streamState}</MetricChip>
                <MetricChip tone="neutral">{finalReport ? "report ready" : "report pending"}</MetricChip>
              </div>
              {intelOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </button>
            {intelOpen ? (
              <div className="nova-dock__body">
                <LiveStream logs={logs} streamState={streamState} hasFinalReport={Boolean(finalReport)} />
              </div>
            ) : null}
          </section>

          <footer className="nova-footer panel-enter">
            <MetricChip tone={backendHealth === "down" ? "error" : "teal"}>Backend {healthLabel}</MetricChip>
            <MetricChip tone="neutral">State {status.label}</MetricChip>
            <MetricChip tone="neutral">Reason codes {startupReasonCodes.length}</MetricChip>
            <MetricChip tone="neutral">Report {finalReport ? "Captured" : "Pending"}</MetricChip>
            <span className="nova-footer__note">Narrative first. Technical confidence stays in appendix by default.</span>
          </footer>
        </div>
      </main>
    );
  }

  return (
    <main className="v5-root" data-run-state={streamState}>
      <div className="v5-shell">
        <header className="studio-header panel-enter">
          <div className="studio-header__identity">
            <p className="topbar__eyebrow">Cloud Hive Editorial Intelligence</p>
            <h1 className="topbar__title">Deep Research Studio</h1>
          </div>
          <div className="studio-header__status">
            <span className={status.barClass}>{status.label}</span>
            <MetricChip tone={backendHealth === "down" ? "error" : "teal"}>
              {backendHealth === "down" ? <WifiOff className="h-3.5 w-3.5" /> : <Wifi className="h-3.5 w-3.5" />}
              API {healthLabel}
            </MetricChip>
            <MetricChip tone="neutral">Mode {DEFAULT_EXECUTION_MODE}</MetricChip>
            <MetricChip tone="neutral">Profile {DEFAULT_RUNTIME_PROFILE}</MetricChip>
          </div>
        </header>

        <section className="studio-controls panel-enter">
          <div className="studio-controls__left">
            <ThemeToggle value={themeMode} onChange={setThemeMode} />
            <MetricChip tone="neutral">Theme {resolvedTheme}</MetricChip>
          </div>
          <div className="studio-controls__right">
            <Button type="button" size="sm" variant="outline" onClick={resetWorkspace} disabled={isSearching}>
              <RefreshCw className="h-3.5 w-3.5" /> Reset
            </Button>
            <Button type="button" size="sm" variant="outline" onClick={stopRun} disabled={!isSearching}>
              <CircleStop className="h-3.5 w-3.5" /> Stop
            </Button>
          </div>
        </section>

        {errorBanner ? (
          <section className="status-banner status-banner--error panel-enter">
            <p className="status-banner__title">{errorBanner.title}</p>
            <p className="status-banner__message">{errorBanner.message}</p>
            <p className="status-banner__action">{errorBanner.action}</p>
          </section>
        ) : null}

        {!errorBanner && providerBanner ? (
          <section className="status-banner status-banner--warn panel-enter">
            <p className="status-banner__title">{providerBanner.title}</p>
            <p className="status-banner__message">{providerBanner.message}</p>
            <p className="status-banner__action">{providerBanner.action}</p>
          </section>
        ) : null}

        <section className="studio-grid">
          <WorkspacePane
            tone="left"
            title="Query Composer"
            subtitle="Define the research question and launch a run."
            actions={<MetricChip tone={status.tone}>{status.label}</MetricChip>}
          >
            <ResearchForm onSearch={handleSearch} isSearching={isSearching} />
            <div className="composer-help">
              <p>{status.detail}</p>
              {shouldShowLiveTimer ? (
                <p className="composer-help__live">Still running. Last update {lastUpdateSeconds}s ago.</p>
              ) : null}
            </div>
          </WorkspacePane>

          <WorkspacePane
            tone="center"
            title="Pipeline Monitor"
            subtitle="Watch stage transitions and compact execution events."
            actions={
              <>
                <MetricChip tone="neutral">{logs.length} events</MetricChip>
                {branchProgress.total > 0 ? (
                  <MetricChip tone="neutral">
                    Branches {branchProgress.completed}/{branchProgress.total}
                  </MetricChip>
                ) : null}
                <MetricChip tone="amber">Live trace</MetricChip>
              </>
            }
          >
            <LiveStream logs={logs} streamState={streamState} hasFinalReport={Boolean(finalReport)} />
          </WorkspacePane>

          <WorkspacePane
            tone="right"
            title="Report Reader"
            subtitle="Summary-first report with chapter navigation and appendix evidence."
            actions={<MetricChip tone={finalReport ? "teal" : streamState === "error" ? "error" : "neutral"}>{finalReport ? "Report ready" : "Awaiting report"}</MetricChip>}
          >
            {finalReport ? (
              <ReportView report={finalReport} />
            ) : (
              <Card className="reader-placeholder">
                <CardHeader className="border-b border-border/70 pb-4">
                  <CardTitle className="text-base font-semibold">Research Report</CardTitle>
                  <CardDescription className="text-sm text-muted-foreground">{reportNotice}</CardDescription>
                </CardHeader>
                <CardContent className="pt-6">
                  {isSearching ? (
                    <div className="space-y-3">
                      <div className="skeleton-line h-4 w-11/12" />
                      <div className="skeleton-line h-4 w-9/12" />
                      <div className="skeleton-line h-4 w-10/12" />
                      <div className="skeleton-line h-4 w-8/12" />
                    </div>
                  ) : (
                    <div className="reader-placeholder__empty">
                      {streamState === "error" ? <AlertTriangle className="h-4 w-4" /> : null}
                      <span>{emptyReportText}</span>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
          </WorkspacePane>
        </section>

        <footer className="studio-footer panel-enter">
          <MetricChip tone={backendHealth === "down" ? "error" : "teal"}>Backend {healthLabel}</MetricChip>
          <MetricChip tone="neutral">State {status.label}</MetricChip>
          <MetricChip tone="neutral">Trace {logs.length}</MetricChip>
          <MetricChip tone="neutral">Report {finalReport ? "Captured" : "Pending"}</MetricChip>
          <span className="diag-strip__note">{status.detail}</span>
        </footer>
      </div>
    </main>
  );
}
