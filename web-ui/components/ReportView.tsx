"use client";

import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  BookOpenText,
  Copy,
  Download,
  ExternalLink,
  FileText,
  LibraryBig,
  ScrollText,
} from "lucide-react";

import { ChapterNav } from "@/components/ui/chapter-nav";
import { Button } from "@/components/ui/button";
import { MetricChip } from "@/components/ui/metric-chip";
import { exportReportPdf } from "@/lib/api";
import { Citation } from "@/lib/types";

type DepthMode = "summary" | "full";
type ReadingMode = "reader" | "evidence";

interface ReportViewProps {
  report: string;
  citations?: Citation[];
  runId?: string;
  metrics?: Record<string, unknown>;
  completedAt?: string;
  qualityProfile?: "strict" | "relaxed";
}

interface Section {
  title: string;
  slug: string;
  markdown: string;
}

const SUMMARY_SECTION_KEYS = new Set([
  "executive summary",
  "background and context",
  "key questions",
  "evidence and findings",
  "deep analysis",
  "implications",
  "recommendations",
  "conclusion",
  "direct answer",
  "key findings",
]);

const EVIDENCE_SECTION_KEYS = new Set([
  "claims",
  "evidence and findings",
  "conflicting evidence",
  "case studies or examples",
  "sources used",
  "evidence confidence summary",
]);

const DEFAULT_LEDGER_EXPANDED =
  process.env.NEXT_PUBLIC_SHOW_RAW_SOURCE_LEDGER_DEFAULT === "true";

function slugify(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9\s-]/g, "").trim().replace(/\s+/g, "-");
}

function normalizeHeading(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9\s-]/g, " ").replace(/\s+/g, " ").trim();
}

function parseSections(report: string): Section[] {
  const text = (report || "").trim();
  if (!text) return [];
  const lines = text.split("\n");
  const sections: Section[] = [];
  let title = "";
  let body: string[] = [];

  const flush = () => {
    if (!title) return;
    sections.push({ title, slug: slugify(title), markdown: body.join("\n").trim() });
  };

  for (const line of lines) {
    const heading = line.trimEnd().match(/^#{1,2}\s+(.+)/);
    if (heading) {
      flush();
      title = heading[1].trim();
      body = [];
      continue;
    }
    body.push(line);
  }
  flush();
  return sections;
}

function markdownToPlain(markdown: string): string {
  return markdown
    .replace(/\[[^\]]+\]\([^)]+\)/g, "")
    .replace(/`+/g, "")
    .replace(/[>#*_\-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function answerFirst(sections: Section[]): string {
  const lead = sections.find((section) =>
    ["executive summary", "direct answer", "background and context"].includes(
      normalizeHeading(section.title),
    ),
  );
  if (!lead) {
    return "Open Full Deep View to inspect the full report, claims register, and sources.";
  }
  const plain = markdownToPlain(lead.markdown);
  return plain.length > 520 ? `${plain.slice(0, 520)}...` : plain;
}

function overallConfidence(citations: Citation[]): { label: string; tone: "teal" | "amber" | "error" } {
  const strong = citations.filter((item) => ["A", "B"].includes(item.source_tier || "")).length;
  const total = Math.max(1, citations.length);
  const ratio = strong / total;
  if (ratio >= 0.55) return { label: "High confidence", tone: "teal" };
  if (ratio >= 0.25) return { label: "Mixed confidence", tone: "amber" };
  return { label: "Constrained confidence", tone: "error" };
}

function sectionConfidence(markdown: string, citations: Citation[]): { label: string; tone: "teal" | "amber" | "error" } {
  const ids = Array.from(markdown.matchAll(/\[(C\d+)\]/g)).map((match) => match[1]);
  const sectionCitations = citations.filter((citation) => ids.includes(citation.claim_id));
  if (!sectionCitations.length) return { label: "Context", tone: "amber" };
  return overallConfidence(sectionCitations);
}

function formatCompletedAt(value?: string): string {
  if (!value) return "Unknown time";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unknown time" : date.toLocaleString();
}

function uniqueDomainCount(citations: Citation[]): number {
  const domains = new Set<string>();
  for (const citation of citations) {
    try {
      if (citation.source_url) domains.add(new URL(citation.source_url).hostname);
    } catch {
      continue;
    }
  }
  return domains.size;
}

function providerMixLabel(citations: Citation[]): string {
  const counts = new Map<string, number>();
  for (const citation of citations) {
    const key = (citation.provider || "unknown").trim().toLowerCase();
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([provider, count]) => `${provider} ${count}`)
    .join(" · ") || "No sources";
}

function renderSources(markdown: string) {
  const markers = [
    "### Full Source Ledger (Detailed Table)",
    "### Full Source Ledger (Heuristic Source Types)",
  ];
  const splitMarker = markers.find((marker) => markdown.includes(marker));
  if (!splitMarker) {
    return (
      <div className="report-markdown report-chapter-body">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown.trim()}</ReactMarkdown>
      </div>
    );
  }
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

export function ReportView({
  report,
  citations = [],
  runId,
  metrics = {},
  completedAt,
  qualityProfile,
}: ReportViewProps) {
  const [depthMode, setDepthMode] = useState<DepthMode>("summary");
  const [readingMode, setReadingMode] = useState<ReadingMode>("reader");
  const [revealing, setRevealing] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [copied, setCopied] = useState(false);

  const sections = useMemo(() => parseSections(report), [report]);
  const answer = useMemo(() => answerFirst(sections), [sections]);
  const confidenceBand = useMemo(() => overallConfidence(citations), [citations]);
  const wordCount = useMemo(() => markdownToPlain(report).split(/\s+/).filter(Boolean).length, [report]);
  const domainCount = useMemo(() => uniqueDomainCount(citations), [citations]);
  const providerSummary = useMemo(() => providerMixLabel(citations), [citations]);
  const sourceCount = citations.length;

  const visibleSections = useMemo(() => {
    let filtered = sections;
    if (readingMode === "evidence") {
      filtered = sections.filter((section) => EVIDENCE_SECTION_KEYS.has(normalizeHeading(section.title)));
    } else if (depthMode === "summary") {
      const summarySections = sections.filter((section) =>
        SUMMARY_SECTION_KEYS.has(normalizeHeading(section.title)),
      );
      filtered = summarySections.length ? summarySections : sections.slice(0, Math.min(5, sections.length));
    }
    return filtered;
  }, [depthMode, readingMode, sections]);

  const constrainedBanner = useMemo(() => {
    if (qualityProfile === "relaxed") return null;
    const lower = report.toLowerCase();
    if (!lower.includes("constrained") && !lower.includes("verification floor")) return null;
    return {
      reason: "This report is constrained by verification/source coverage limits in this run.",
      action: "Next step: rerun with stronger primary sources or expanded provider capacity to lift constrained findings.",
    };
  }, [qualityProfile, report]);

  useEffect(() => {
    setRevealing(true);
    const timer = window.setTimeout(() => setRevealing(false), 220);
    return () => window.clearTimeout(timer);
  }, [depthMode, readingMode, report]);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(report);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };

  const handleDownloadPdf = async () => {
    setExporting(true);
    try {
      const blob = await exportReportPdf({
        runId: runId || `report-${Date.now()}`,
        report,
        citations,
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${(runId || "research-report").replace(/[^a-z0-9-]/gi, "-").toLowerCase()}.pdf`;
      anchor.click();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  };

  if (!report) return null;

  return (
    <div className="reader-shell">
      <header className="reader-header">
        <div>
          <p className="reader-header__eyebrow">Report</p>
          <h2 className="reader-header__title">
            <FileText className="h-4 w-4" /> Research Report
          </h2>
          <p className="reader-header__subtitle">
            Publication-style narrative with a separate evidence register and export actions.
          </p>
        </div>
        <div className="reader-header__controls">
          <MetricChip tone={confidenceBand.tone}>{confidenceBand.label}</MetricChip>
          <MetricChip tone="neutral">{wordCount.toLocaleString()} words</MetricChip>
          <MetricChip tone="neutral">{sourceCount} sources</MetricChip>
        </div>
      </header>

      <div className="report-toolbar">
        <div className="report-mode-row">
          <Button type="button" size="sm" variant={depthMode === "summary" ? "default" : "outline"} onClick={() => setDepthMode("summary")}>
            Summary View
          </Button>
          <Button type="button" size="sm" variant={depthMode === "full" ? "default" : "outline"} onClick={() => setDepthMode("full")}>
            Full Deep View
          </Button>
        </div>
        <div className="report-mode-row">
          <Button type="button" size="sm" variant={readingMode === "reader" ? "default" : "outline"} onClick={() => setReadingMode("reader")}>
            <ScrollText className="h-4 w-4" /> Reader View
          </Button>
          <Button type="button" size="sm" variant={readingMode === "evidence" ? "default" : "outline"} onClick={() => setReadingMode("evidence")}>
            <LibraryBig className="h-4 w-4" /> Evidence View
          </Button>
        </div>
        <div className="report-actions">
          <Button type="button" size="sm" variant="outline" onClick={handleCopy}>
            <Copy className="h-4 w-4" /> {copied ? "Copied" : "Copy Markdown"}
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={() => (window.location.hash = "#sources-used")}>
            <ExternalLink className="h-4 w-4" /> Open Sources
          </Button>
          <Button type="button" size="sm" onClick={handleDownloadPdf} disabled={exporting}>
            <Download className={`h-4 w-4${exporting ? " animate-pulse" : ""}`} />
            {exporting ? "Exporting..." : "Download PDF"}
          </Button>
        </div>
      </div>

      <div className="report-meta-strip">
        <MetricChip tone="neutral">Diversity {domainCount} domains</MetricChip>
        <MetricChip tone="neutral">{providerSummary}</MetricChip>
        <MetricChip tone="neutral">Generated {formatCompletedAt(completedAt)}</MetricChip>
        {"method_trace_summary" in metrics ? <MetricChip tone="neutral">Target met</MetricChip> : null}
      </div>

      <section className="reader-answer">
        <p className="reader-answer__label">Answer first</p>
        <p className="reader-answer__text">{answer}</p>
        <p className="reader-answer__hint">
          {readingMode === "reader"
            ? "Switch to Evidence View for claims, source diversity, and appendix detail."
            : "Evidence View surfaces claims, conflicts, examples, and the full source ledger."}
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
        <div className="report-scroll">
          <div className="report-book">
            {visibleSections.map((section, index) => {
              const sectionBand = sectionConfidence(section.markdown, citations);
              return (
                <article
                  key={section.slug}
                  id={section.slug}
                  className={`report-chapter ${revealing ? "report-chapter--reveal" : ""}`}
                  style={revealing ? { animationDelay: `${Math.min(index, 8) * 36}ms` } : undefined}
                >
                  <div className="report-chapter__head">
                    <h2>
                      <BookOpenText className="h-4 w-4" /> {section.title}
                    </h2>
                    <MetricChip tone={sectionBand.tone}>{sectionBand.label}</MetricChip>
                  </div>
                  {section.title === "Sources Used" ? (
                    renderSources(section.markdown)
                  ) : (
                    <div className="report-markdown report-chapter-body">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{section.markdown}</ReactMarkdown>
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
