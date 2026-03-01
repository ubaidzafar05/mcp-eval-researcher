import * as React from "react";

import { cn } from "@/lib/utils";

interface MetricChipProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: "neutral" | "teal" | "amber" | "error";
}

const toneClass: Record<NonNullable<MetricChipProps["tone"]>, string> = {
  neutral: "metric-chip",
  teal: "metric-chip metric-chip--teal",
  amber: "metric-chip metric-chip--amber",
  error: "metric-chip metric-chip--error",
};

export function MetricChip({ className, tone = "neutral", ...props }: MetricChipProps) {
  return <span className={cn(toneClass[tone], className)} {...props} />;
}
