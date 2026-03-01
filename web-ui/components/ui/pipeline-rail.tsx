import * as React from "react";

import { cn } from "@/lib/utils";

export type PipelineStage = "planning" | "research" | "synthesis" | "evaluation" | "finalizing" | "final";
export type PipelineStageState = "pending" | "active" | "completed" | "error";

export interface PipelineNode {
  key: PipelineStage;
  label: string;
  state: PipelineStageState;
  elapsedSec?: number;
}

interface PipelineRailProps {
  nodes: PipelineNode[];
}

export function PipelineRail({ nodes }: PipelineRailProps) {
  return (
    <div className="pipeline-rail-scroll">
      <div className="pipeline-rail" role="list" aria-label="Execution pipeline">
        {nodes.map((node, index) => (
          <React.Fragment key={node.key}>
            <div className="pipeline-node-wrap" role="listitem">
              <div
                className={cn(
                  "pipeline-node",
                  `pipeline-node--${node.state}`,
                  node.key === "final" ? "pipeline-node--terminal" : "",
                )}
                title={node.elapsedSec ? `${node.elapsedSec}s in stage` : undefined}
              >
                <span className="pipeline-node__dot" />
                <span className="pipeline-node__label">{node.label}</span>
                {typeof node.elapsedSec === "number" && node.state === "active" ? (
                  <span className="pipeline-node__timer">{node.elapsedSec}s</span>
                ) : null}
              </div>
            </div>
            {index < nodes.length - 1 ? (
              <div
                className={cn(
                  "pipeline-edge",
                  node.state === "completed" && nodes[index + 1]?.state === "active" ? "pipeline-edge--live" : "",
                  node.state === "completed" && nodes[index + 1]?.state === "completed"
                    ? "pipeline-edge--completed"
                    : "",
                )}
                aria-hidden="true"
              />
            ) : null}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}
