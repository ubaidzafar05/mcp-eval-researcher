"use client";

import { FormEvent, useMemo, useState } from "react";
import { Loader2, Search, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { MetricChip } from "@/components/ui/metric-chip";
import { Textarea } from "@/components/ui/textarea";

interface ResearchFormProps {
  onSearch: (query: string) => void;
  isSearching: boolean;
}

function qualityLabel(words: number): { label: string; tone: "teal" | "amber" | "error"; hint: string } {
  if (words >= 16) {
    return {
      label: "Strong prompt",
      tone: "teal",
      hint: "Excellent specificity. This should improve evidence quality and final report depth.",
    };
  }
  if (words >= 8) {
    return {
      label: "Usable prompt",
      tone: "amber",
      hint: "Add one concrete constraint (region, timeframe, metric, or source type).",
    };
  }
  return {
    label: "Needs detail",
    tone: "error",
    hint: "Short prompts often produce generic findings. Add intent and expected outcome.",
  };
}

function runProfile(words: number): string {
  if (words >= 16) return "Deep profile";
  if (words >= 8) return "Balanced profile";
  return "Fast profile";
}

export function ResearchForm({ onSearch, isSearching }: ResearchFormProps) {
  const [query, setQuery] = useState("");

  const stats = useMemo(() => {
    const trimmed = query.trim();
    const words = trimmed ? trimmed.split(/\s+/).length : 0;
    return {
      words,
      chars: trimmed.length,
      quality: qualityLabel(words),
      profile: runProfile(words),
    };
  }, [query]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || isSearching) {
      return;
    }
    onSearch(trimmed);
  };

  return (
    <form onSubmit={handleSubmit} className="composer-form">
      <div className="composer-toolbar">
        <MetricChip tone={stats.quality.tone}>{stats.quality.label}</MetricChip>
        <MetricChip tone="neutral">{stats.profile}</MetricChip>
        <MetricChip tone="neutral">{stats.words} words</MetricChip>
        <MetricChip tone="neutral">{stats.chars} chars</MetricChip>
      </div>

      <label className="composer-label">Research Question</label>
      <Textarea
        name="query"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Example: Compare AI detector methods for long-form blogs, including false-positive behavior, adversarial robustness, and practical hardening controls."
        className="composer-textarea"
        required
        disabled={isSearching}
      />

      <div className="composer-guidance">
        <Sparkles className="h-3.5 w-3.5" />
        <p>{stats.quality.hint}</p>
      </div>

      <Button type="submit" size="lg" className="composer-submit" disabled={isSearching || !query.trim()}>
        {isSearching ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Running Research Pipeline...
          </>
        ) : (
          <>
            <Search className="mr-2 h-4 w-4" /> Start Deep Research
          </>
        )}
      </Button>
    </form>
  );
}
