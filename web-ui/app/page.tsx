"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  BookText,
  CircleStop,
  RefreshCw,
  Wifi,
  WifiOff,
} from "lucide-react";

import { LiveStream } from "@/components/LiveStream";
import { ReportView } from "@/components/ReportView";
import { ResearchForm } from "@/components/ResearchForm";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { MetricChip } from "@/components/ui/metric-chip";
import { ThemeMode, ThemeToggle } from "@/components/ui/theme-toggle";
import { DEFAULT_EXECUTION_MODE, DEFAULT_QUALITY_PROFILE, DEFAULT_RUNTIME_PROFILE } from "@/lib/api";
import { useResearchRun } from "@/lib/hooks/useResearchRun";
import { RunBannerReason, StreamState } from "@/lib/types";

type ThemeResolved = "light" | "dark";
const DEFAULT_THEME_MODE: ThemeMode =
  process.env.NEXT_PUBLIC_DEFAULT_THEME === "light" || process.env.NEXT_PUBLIC_DEFAULT_THEME === "dark"
    ? process.env.NEXT_PUBLIC_DEFAULT_THEME
    : "light";
const THEME_STORAGE_KEY = "cloudhive.theme_mode";

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
  const {
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
  } = useResearchRun();
  const [themeMode, setThemeMode] = useState<ThemeMode>(DEFAULT_THEME_MODE);

  const themeBootstrappedRef = useRef(false);

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
      document.documentElement.dataset.theme = nextResolved;
    };
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", handleChange);
      return () => media.removeEventListener("change", handleChange);
    }
    media.addListener(handleChange);
    return () => media.removeListener(handleChange);
  }, [themeMode]);

  const resetWorkspace = () => {
    resetRun();
  };

  const status = STATUS_META[streamState];
  const shouldShowLiveTimer =
    isSearching && (streamState === "connecting" || streamState === "running") && lastProgressAt !== null;
  const lastUpdateSeconds =
    lastProgressAt !== null ? Math.max(0, Math.floor((nowTick - lastProgressAt) / 1000)) : 0;
  const activeStageLabel = useMemo(() => {
    if (activeStage === "planning") return "Planning";
    if (activeStage === "research") return "Research";
    if (activeStage === "synthesis") return "Synthesis";
    if (activeStage === "evaluation") return "Evaluation";
    if (activeStage === "finalizing") return "Finalizing";
    if (activeStage === "final") return "Final";
    return "Current stage";
  }, [activeStage]);

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

  return (
    <main className="nova-root" data-run-state={streamState}>
      <div className="nova-shell">
        <header className="nova-topbar panel-enter">
          <div className="nova-brand">
            <p className="nova-brand__eyebrow">Cloud Hive Research OS</p>
            <h1 className="nova-brand__title">Research Control Room</h1>
          </div>
          <div className="nova-topbar__stack">
            <div className="nova-topbar__meta">
              <MetricChip tone={backendHealth === "down" ? "error" : "teal"}>
                {backendHealth === "down" ? <WifiOff className="h-3.5 w-3.5" /> : <Wifi className="h-3.5 w-3.5" />}
                API {healthLabel}
              </MetricChip>
              <MetricChip tone="neutral">{status.label}</MetricChip>
              <MetricChip tone="neutral">Mode {DEFAULT_EXECUTION_MODE}</MetricChip>
              <MetricChip tone="neutral">Profile {DEFAULT_RUNTIME_PROFILE}</MetricChip>
            </div>
            <div className="nova-topbar__actions">
              <ThemeToggle value={themeMode} onChange={setThemeMode} />
              <Button type="button" size="sm" variant="outline" onClick={resetWorkspace} disabled={isSearching}>
                <RefreshCw className="h-3.5 w-3.5" /> Reset
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={stopRun} disabled={!isSearching}>
                <CircleStop className="h-3.5 w-3.5" /> Stop
              </Button>
            </div>
          </div>
        </header>

        {bannerConfig ? (
          <section className={`nova-banner panel-enter ${bannerConfig.tone === "error" ? "nova-banner--error" : "nova-banner--warn"}`}>
            <p className="nova-banner__title">{bannerConfig.title}</p>
            <p className="nova-banner__message">{bannerConfig.message}</p>
            <p className="nova-banner__action">{bannerConfig.action}</p>
          </section>
        ) : null}

        <section className="nova-body">
          <aside className="nova-control">
            <section className="nova-panel nova-panel--command panel-enter">
              <header className="nova-panel__head">
                <div>
                  <p className="nova-panel__eyebrow">Command</p>
                  <h2 className="nova-panel__title">Research Command</h2>
                </div>
                <MetricChip tone={status.tone}>{status.label}</MetricChip>
              </header>
              <div className="nova-panel__body">
                <ResearchForm onSearch={startRun} isSearching={isSearching} />
              </div>
              {shouldShowLiveTimer ? (
                <div className="nova-panel__foot">
                  <p className="nova-panel__live">{activeStageLabel} {lastUpdateSeconds}s</p>
                </div>
              ) : null}
            </section>

            <section className="nova-panel nova-panel--monitor panel-enter">
              <header className="nova-panel__head">
                <div>
                  <p className="nova-panel__eyebrow">Monitor</p>
                  <h2 className="nova-panel__title">Live Pipeline</h2>
                </div>
              </header>
              <div className="nova-panel__body nova-panel__body--monitor">
                <LiveStream
                  logs={logs}
                  streamState={streamState}
                  hasFinalReport={Boolean(finalReport)}
                  nowTick={nowTick}
                  activeStage={
                    activeStage === "research" ||
                    activeStage === "synthesis" ||
                    activeStage === "evaluation" ||
                    activeStage === "finalizing" ||
                    activeStage === "final"
                      ? activeStage
                      : "planning"
                  }
                  stageStartedAt={lastProgressAt}
                />
              </div>
            </section>
          </aside>

          <section className="nova-report">
            <header className="nova-report__head panel-enter">
              <div>
                <p className="nova-report__eyebrow">Report studio</p>
                <h2 className="nova-report__title">
                  <BookText className="h-4 w-4" /> Research Narrative
                </h2>
              </div>
              <div className="nova-report__chips">
                <MetricChip tone={finalReport ? "teal" : "neutral"}>
                  {finalReport ? "Report ready" : "Awaiting report"}
                </MetricChip>
              </div>
            </header>

            <div className="nova-report__body panel-enter">
              {finalReport ? (
                <ReportView
                  report={finalReport}
                  citations={finalCitations}
                  runId={finalRunId}
                  metrics={finalMetrics}
                  completedAt={completedAt}
                  qualityProfile={DEFAULT_QUALITY_PROFILE}
                />
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

        <footer className="nova-footer panel-enter">
          <MetricChip tone={backendHealth === "down" ? "error" : "teal"}>Backend {healthLabel}</MetricChip>
          <MetricChip tone="neutral">State {status.label}</MetricChip>
          <MetricChip tone="neutral">Events {logs.length}</MetricChip>
          <MetricChip tone="neutral">Report {finalReport ? "Ready" : "Pending"}</MetricChip>
        </footer>
      </div>
    </main>
  );
}
