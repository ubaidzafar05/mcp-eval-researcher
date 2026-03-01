"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, Sparkles } from "lucide-react";

import { MetricChip } from "@/components/ui/metric-chip";
import { PipelineNode, PipelineRail, PipelineStage, PipelineStageState } from "@/components/ui/pipeline-rail";
import { ScrollArea } from "@/components/ui/scroll-area";

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

interface LiveStreamProps {
  logs: LogEvent[];
  streamState: "idle" | "connecting" | "running" | "final" | "error";
  hasFinalReport: boolean;
}

interface TraceRow {
  type: "status" | "token" | "error" | "done";
  stage: PipelineStage;
  message: string;
  timestamp: string;
  tokenCount?: number;
  details?: string[];
}

const STAGE_ORDER: PipelineStage[] = [
  "planning",
  "research",
  "synthesis",
  "evaluation",
  "finalizing",
  "final",
];

const STAGE_LABEL: Record<PipelineStage, string> = {
  planning: "Plan",
  research: "Research",
  synthesis: "Synthesize",
  evaluation: "Evaluate",
  finalizing: "Finalize",
  final: "Done",
};

const STAGE_MAP: Record<string, PipelineStage> = {
  connecting: "planning",
  connected: "planning",
  starting: "planning",
  accepted: "planning",
  decomposition: "planning",
  planner_decompose: "planning",
  queued: "planning",
  fallback: "planning",
  planning: "planning",
  research_pool: "research",
  fanout: "research",
  sub_research: "research",
  research: "research",
  researcher: "research",
  merge: "synthesis",
  synthesis: "synthesis",
  synthesizer: "synthesis",
  self_correction: "synthesis",
  self_correction_retry: "synthesis",
  evaluation: "evaluation",
  eval_gate: "evaluation",
  hitl: "evaluation",
  finalizing: "finalizing",
  finalize: "finalizing",
  final: "final",
};

function normalizeStage(log: LogEvent): PipelineStage {
  const raw = (log.active_stage || log.stage || "").toLowerCase();
  if (STAGE_MAP[raw]) {
    return STAGE_MAP[raw];
  }
  if (log.type === "token") {
    return "synthesis";
  }
  return "planning";
}

function isHeartbeatStatus(log: LogEvent): boolean {
  if (log.type !== "status") {
    return false;
  }
  if (log.is_heartbeat) {
    return true;
  }
  const msg = (log.message || "").toLowerCase();
  return (
    msg.includes("still processing sources and synthesis") ||
    msg.includes("distributed worker processing query") ||
    msg.includes("still running")
  );
}

function summarize(log: LogEvent): string {
  if (log.type === "status") {
    if (log.warned_idle && typeof log.idle_sec === "number" && typeof log.idle_threshold_sec === "number") {
      return `${log.message || "Running slowly"} (${log.idle_sec}s/${log.idle_threshold_sec}s)`;
    }
    return log.message || (log.stage ? log.stage.replaceAll("_", " ") : "status update");
  }
  if (log.type === "token") {
    const text = (log.content || "").replace(/\s+/g, " ").trim();
    if (!text) return "Streaming model output.";
    return text.length > 140 ? `${text.slice(0, 140)}...` : text;
  }
  if (log.type === "error") {
    return log.message || "Pipeline error";
  }
  return "Pipeline complete.";
}

function compactLogs(logs: LogEvent[]): TraceRow[] {
  const rows: TraceRow[] = [];

  for (const log of logs) {
    const stage = normalizeStage(log);
    const message = summarize(log);
    const last = rows[rows.length - 1];

    if (log.type === "token") {
      if (last && last.type === "token" && last.stage === stage) {
        last.tokenCount = (last.tokenCount || 1) + 1;
        if (log.content) {
          const cleaned = log.content.replace(/\s+/g, " ").trim();
          if (cleaned && (last.details?.length || 0) < 5) {
            last.details = [...(last.details || []), cleaned.slice(0, 220)];
          }
        }
        last.timestamp = log.timestamp;
        continue;
      }

      rows.push({
        type: "token",
        stage,
        message: "Streaming synthesis output.",
        timestamp: log.timestamp,
        tokenCount: 1,
        details: log.content ? [log.content.replace(/\s+/g, " ").trim().slice(0, 220)] : undefined,
      });
      continue;
    }

    if (
      log.type === "status" &&
      last &&
      last.type === "status" &&
      last.stage === stage &&
      last.message === message
    ) {
      last.timestamp = log.timestamp;
      continue;
    }

    rows.push({
      type: log.type,
      stage,
      message,
      timestamp: log.timestamp,
      details:
        log.query || (log.reason_codes && log.reason_codes.length > 0)
          ? [
              ...(log.query ? [log.query] : []),
              ...(log.reason_codes && log.reason_codes.length > 0
                ? [`reason_codes: ${log.reason_codes.join(", ")}`]
                : []),
            ]
          : undefined,
    });
  }

  return rows.slice(-220);
}

function buildPipelineNodes(
  logs: LogEvent[],
  streamState: LiveStreamProps["streamState"],
  hasFinalReport: boolean,
  elapsedSec?: number,
): PipelineNode[] {
  const statusMap = new Map<PipelineStage, PipelineStageState>();
  for (const stage of STAGE_ORDER) {
    statusMap.set(stage, "pending");
  }

  let activeStage: PipelineStage = streamState === "idle" ? "planning" : "planning";
  let furthestStageIndex = 0;

  for (const log of logs) {
    if (isHeartbeatStatus(log)) {
      continue;
    }
    let stage = normalizeStage(log);
    const candidateStageIndex = STAGE_ORDER.indexOf(stage);
    if (candidateStageIndex > furthestStageIndex) {
      furthestStageIndex = candidateStageIndex;
    }
    if (candidateStageIndex < furthestStageIndex && log.type !== "error" && log.type !== "done") {
      stage = STAGE_ORDER[furthestStageIndex];
    }
    activeStage = stage;
    if (log.type === "error") {
      statusMap.set(stage, "error");
      break;
    }

    if (log.type === "done") {
      if (hasFinalReport) {
        statusMap.set("final", "completed");
      } else {
        statusMap.set(activeStage, "error");
      }
      continue;
    }

    if (log.type === "status") {
      const stageIndex = STAGE_ORDER.indexOf(stage);
      for (let idx = 0; idx < stageIndex; idx += 1) {
        const s = STAGE_ORDER[idx];
        if (statusMap.get(s) !== "error") {
          statusMap.set(s, "completed");
        }
      }
      if (statusMap.get(stage) !== "error") {
        statusMap.set(stage, "active");
      }
    }
  }

  if (streamState === "final" && hasFinalReport) {
    for (const stage of STAGE_ORDER) {
      statusMap.set(stage, "completed");
    }
    activeStage = "final";
  }

  if (streamState === "error" && logs.length === 0) {
    statusMap.set("planning", "error");
    activeStage = "planning";
  }

  return STAGE_ORDER.map((stage) => ({
    key: stage,
    label: STAGE_LABEL[stage],
    state: statusMap.get(stage) ?? "pending",
    elapsedSec: stage === activeStage && statusMap.get(stage) === "active" ? elapsedSec : undefined,
  }));
}

export function LiveStream({ logs, streamState, hasFinalReport }: LiveStreamProps) {
  const monitorRef = useRef<HTMLDivElement>(null);
  const [nowTick, setNowTick] = useState(Date.now());
  const [activeSince, setActiveSince] = useState<number | null>(null);
  const [activeStage, setActiveStage] = useState<PipelineStage | null>(null);

  useEffect(() => {
    const viewport = monitorRef.current?.querySelector("[data-radix-scroll-area-viewport]") as HTMLElement | null;
    if (!viewport) {
      return;
    }
    viewport.scrollTop = viewport.scrollHeight;
  }, [logs]);

  useEffect(() => {
    if (streamState !== "running" && streamState !== "connecting") {
      return;
    }
    const timer = window.setInterval(() => setNowTick(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [streamState]);

  const visibleRows = useMemo(() => compactLogs(logs), [logs]);

  const currentStage = useMemo<PipelineStage | null>(() => {
    const meaningful = logs.filter((log) => !isHeartbeatStatus(log));
    if (meaningful.length === 0) {
      return streamState === "idle" ? null : "planning";
    }
    const last = meaningful[meaningful.length - 1];
    return normalizeStage(last);
  }, [logs, streamState]);

  useEffect(() => {
    if (!currentStage) {
      setActiveStage(null);
      setActiveSince(null);
      return;
    }
    if (currentStage !== activeStage) {
      setActiveStage(currentStage);
      setActiveSince(Date.now());
    }
  }, [activeStage, currentStage]);

  const elapsedSec = activeSince ? Math.max(0, Math.floor((nowTick - activeSince) / 1000)) : undefined;

  const nodes = useMemo(
    () => buildPipelineNodes(logs, streamState, hasFinalReport, elapsedSec),
    [logs, streamState, hasFinalReport, elapsedSec],
  );

  const stagesReached = useMemo(
    () => new Set(logs.filter((log) => log.type === "status").map((log) => normalizeStage(log))).size,
    [logs],
  );
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

  const latestStage = useMemo(() => {
    const activeNode = nodes.find((node) => node.state === "active" || node.state === "error");
    if (activeNode) return activeNode.label;
    if (streamState === "final") return "Final";
    return "Waiting";
  }, [nodes, streamState]);

  return (
    <div ref={monitorRef} className="monitor-shell">
      <div className="monitor-meta-row">
        <MetricChip tone="neutral">{logs.length} events</MetricChip>
        <MetricChip tone="neutral">{stagesReached} stages</MetricChip>
        {branchProgress.total > 0 ? (
          <MetricChip tone="neutral">
            Branches {branchProgress.completed}/{branchProgress.total}
          </MetricChip>
        ) : null}
        <MetricChip tone={streamState === "error" ? "error" : streamState === "running" ? "teal" : "amber"}>
          Active {latestStage}
        </MetricChip>
      </div>

      <PipelineRail nodes={nodes} />

      <div className="monitor-stage-note">
        <p>Stage transitions are animated and grouped. Repeated token-level events are compacted automatically.</p>
      </div>

      <ScrollArea className="monitor-events">
        <div className="space-y-2.5 font-mono text-xs">
          {visibleRows.length === 0 ? (
            <div className="trace-empty">Waiting for execution events...</div>
          ) : (
            visibleRows.map((row, idx) => {
              const className =
                row.type === "error"
                  ? "trace-event trace-event--error"
                  : row.type === "token"
                    ? "trace-event trace-event--token"
                    : "trace-event trace-event--status";

              return (
                <div
                  key={`${row.timestamp}-${idx}`}
                  className={`trace-row ${className}`}
                  style={{ animationDelay: `${Math.min(idx, 26) * 10}ms` }}
                >
                  <div className="trace-event__meta">
                    <span className="trace-event__time">{row.timestamp}</span>
                    <span className="trace-event__badges">
                      {row.type === "status" && <Loader2 className="h-3 w-3 animate-spin" />}
                      {row.type === "token" && <Sparkles className="h-3 w-3" />}
                      {row.type === "error" && <AlertCircle className="h-3 w-3" />}
                      {row.type === "done" && <CheckCircle2 className="h-3 w-3" />}
                      <MetricChip tone="neutral">{row.type}</MetricChip>
                      <MetricChip tone="neutral">{STAGE_LABEL[row.stage]}</MetricChip>
                    </span>
                  </div>

                  <p className={`trace-event__message ${row.type === "token" ? "trace-event__message--token" : ""}`}>
                    {row.message}
                    {row.type === "token" && row.tokenCount ? ` (${row.tokenCount} chunks)` : ""}
                  </p>

                  {row.details && row.details.length > 0 ? (
                    <details className="trace-details">
                      <summary>Show details</summary>
                      <pre>{row.details.join("\n\n")}</pre>
                    </details>
                  ) : null}
                </div>
              );
            })
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
