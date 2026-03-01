import * as React from "react";

import { cn } from "@/lib/utils";

interface WorkspacePaneProps extends React.HTMLAttributes<HTMLDivElement> {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
  tone?: "left" | "center" | "right";
}

export function WorkspacePane({
  title,
  subtitle,
  actions,
  tone = "center",
  className,
  children,
  ...props
}: WorkspacePaneProps) {
  return (
    <section className={cn("workspace-pane", `workspace-pane--${tone}`, className)} {...props}>
      <header className="workspace-pane__header">
        <div className="workspace-pane__title-wrap">
          <p className="workspace-pane__title">{title}</p>
          {subtitle ? <p className="workspace-pane__subtitle">{subtitle}</p> : null}
        </div>
        {actions ? <div className="workspace-pane__actions">{actions}</div> : null}
      </header>
      <div className="workspace-pane__body">{children}</div>
    </section>
  );
}
