"use client";

import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { BookOpenText, FileText } from "lucide-react";

import { ChapterNav } from "@/components/ui/chapter-nav";
import { Button } from "@/components/ui/button";
import { MetricChip } from "@/components/ui/metric-chip";

type ReportReaderMode = "summary" | "full";

interface ReportViewProps {
  report: string;
}

interface Section {
  title: string;
  slug: string;
  markdown: string;
}

const SUMMARY_SECTION_KEYS = new Set([
  "abstract",
  "introduction",
  "theoretical framework",
  "methodology",
  "empirical results",
  "conclusion",
  "executive summary",
  "direct answer",
  "key findings",
  "verified findings register",
  "recommendations",
]);

const DEFAULT_LEDGER_EXPANDED =
  process.env.NEXT_PUBLIC_SHOW_RAW_SOURCE_LEDGER_DEFAULT === "true";

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-");
}

function normalizeHeading(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function parseSections(report: string): Section[] {
  const text = (report || "").trim();
  if (!text) {
    return [];
  }

  const lines = text.split("\n");
  const sections: Section[] = [];
  let currentTitle = "";
  let currentLines: string[] = [];

  const flush = () => {
    if (!currentTitle) {
      return;
    }
    sections.push({
      title: currentTitle,
      slug: slugify(currentTitle),
      markdown: currentLines.join("\n").trim(),
    });
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (line.startsWith("## ")) {
      flush();
      currentTitle = line.replace(/^##\s+/, "").trim();
      currentLines = [];
      continue;
    }
    currentLines.push(rawLine);
  }

  flush();
  return sections;
}

function markdownToPlain(markdown: string): string {
  return markdown
    .replace(/\[[^\]]+\]\([^\)]+\)/g, "")
    .replace(/`+/g, "")
    .replace(/[>#*_\-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function answerFirst(sections: Section[]): string {
  const direct = sections.find((section) => section.title === "Direct Answer");
  const abstract = sections.find((section) => section.title === "Abstract");
  const executive = sections.find((section) => section.title === "Executive Summary");
  const intro = sections.find((section) => section.title === "Introduction");
  const leadSection = direct ?? abstract ?? executive ?? intro;
  if (!leadSection) {
    return "Open Full Deep View to inspect chapter-level findings and evidence appendix.";
  }

  const plain = markdownToPlain(leadSection.markdown).replace(
    /tier summary is missing in this payload\.?/gi,
    "",
  );
  if (!plain) {
    return "Top narrative section is empty. Open Full Deep View for full report context.";
  }

  return plain.length > 500 ? `${plain.slice(0, 500)}...` : plain;
}

function renderSources(markdown: string) {
  const splitMarker = "### Full Source Ledger (Detailed Table)";
  const [snapshot, ledger] = markdown.split(splitMarker);

  return (
    <div className="space-y-3">
      <div className="report-markdown report-chapter-body">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{snapshot?.trim() ?? ""}</ReactMarkdown>
      </div>

      {ledger ? (
        <details className="report-appendix" open={DEFAULT_LEDGER_EXPANDED}>
          <summary>Show Full Source Ledger</summary>
          <div className="report-markdown report-chapter-body mt-3">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {`${splitMarker}\n${ledger.trim()}`}
            </ReactMarkdown>
          </div>
        </details>
      ) : null}
    </div>
  );
}

export function ReportView({ report }: ReportViewProps) {
  const [mode, setMode] = useState<ReportReaderMode>("summary");
  const [revealing, setRevealing] = useState(true);

  const sections = useMemo(() => parseSections(report), [report]);
  const visibleSections = useMemo(() => {
    if (mode === "full") {
      return sections;
    }
    const filtered = sections.filter((section) =>
      SUMMARY_SECTION_KEYS.has(normalizeHeading(section.title)),
    );
    if (filtered.length > 0) {
      return filtered;
    }
    return sections.slice(0, Math.min(5, sections.length));
  }, [mode, sections]);

  const answer = useMemo(() => answerFirst(sections), [sections]);

  const confidenceBand = useMemo(() => {
    const compactMatch = report.match(/Source tiers:\s*A=(\d+),\s*B=(\d+),\s*C=(\d+)/i);
    const verboseMatch = report.match(/Source quality mix:\s*Tier A=(\d+),\s*Tier B=(\d+),\s*Tier C=(\d+)/i);
    const match = compactMatch ?? verboseMatch;
    if (!match) {
      return {
        label: "Confidence unknown",
        tone: "amber" as const,
        detail: "Open Full Deep View to inspect verification details and appendix evidence.",
      };
    }

    const a = Number(match[1] ?? 0);
    const b = Number(match[2] ?? 0);
    const c = Number(match[3] ?? 0);
    const total = Math.max(1, a + b + c);
    const ratio = (a + b) / total;

    if (ratio >= 0.5) {
      return {
        label: "High confidence",
        tone: "teal" as const,
        detail: "Core findings are backed by stronger corroborated evidence.",
      };
    }
    if (ratio >= 0.2) {
      return {
        label: "Mixed confidence",
        tone: "amber" as const,
        detail: "Some conclusions are directional; validate critical decisions in the appendix.",
      };
    }
    return {
      label: "Constrained confidence",
      tone: "error" as const,
      detail: "Use this report directionally until missing verification fields are resolved.",
    };
  }, [report]);

  const constrainedBanner = useMemo(() => {
    const lower = report.toLowerCase();
    if (
      !lower.includes("constrained")
      && !lower.includes("verification floor")
      && !lower.includes("provider_quota_exhausted")
    ) {
      return null;
    }
    return {
      reason:
        "This report is constrained by verification/source coverage limits in this run.",
      action:
        "Next step: rerun with stronger primary sources or expanded provider capacity to lift constrained findings.",
    };
  }, [report]);

  useEffect(() => {
    setRevealing(true);
    const timer = window.setTimeout(() => setRevealing(false), 260);
    return () => window.clearTimeout(timer);
  }, [report, mode]);

  if (!report) {
    return null;
  }

  return (
    <div className="reader-shell">
      <header className="reader-header">
        <div>
          <p className="reader-header__eyebrow">Editorial report reader</p>
          <h2 className="reader-header__title">
            <FileText className="h-4 w-4" /> Final Research Report
          </h2>
          <p className="reader-header__subtitle">
            Narrative-first reading flow with chapter cards and collapsible evidence appendix.
          </p>
        </div>

        <div className="reader-header__controls">
          {mode === "full" ? <MetricChip tone={confidenceBand.tone}>{confidenceBand.label}</MetricChip> : null}
          <MetricChip tone="neutral">{mode === "summary" ? "Summary" : "Full deep"}</MetricChip>
        </div>
      </header>

      <div className="report-mode-row">
        <Button type="button" size="sm" variant={mode === "summary" ? "default" : "outline"} onClick={() => setMode("summary")}>
          Summary View
        </Button>
        <Button type="button" size="sm" variant={mode === "full" ? "default" : "outline"} onClick={() => setMode("full")}>
          Full Deep View
        </Button>
      </div>

      <section className="reader-answer">
        <p className="reader-answer__label">Answer first</p>
        <p className="reader-answer__text">{answer}</p>
        <p className="reader-answer__hint">
          {mode === "summary"
            ? "Decision narrative first. Technical confidence and full source ledger are in Full Deep View."
            : confidenceBand.detail}
        </p>
      </section>

      {constrainedBanner ? (
        <section className="status-banner status-banner--warn">
          <p className="status-banner__title">Constrained output</p>
          <p className="status-banner__message">{constrainedBanner.reason}</p>
          <p className="status-banner__action">{constrainedBanner.action}</p>
        </section>
      ) : null}

      <div className="reader-layout">
        <ChapterNav items={visibleSections.map((section) => ({ slug: section.slug, title: section.title }))} />

        <div className="report-book">
          {visibleSections.map((section, index) => (
            <article
              key={section.slug}
              id={section.slug}
              className={`report-chapter ${revealing ? "report-chapter--reveal" : ""}`}
              style={revealing ? { animationDelay: `${Math.min(index, 8) * 36}ms` } : undefined}
            >
              <h2>
                <BookOpenText className="h-4 w-4" /> {section.title}
              </h2>
              {section.title === "Sources Used" ? (
                renderSources(section.markdown)
              ) : (
                <div className="report-markdown report-chapter-body">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{section.markdown}</ReactMarkdown>
                </div>
              )}
            </article>
          ))}
        </div>
      </div>
    </div>
  );
}
