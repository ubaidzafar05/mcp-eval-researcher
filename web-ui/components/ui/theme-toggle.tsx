"use client";

import * as React from "react";
import { Laptop2, Moon, Sun } from "lucide-react";

import { cn } from "@/lib/utils";

export type ThemeMode = "system" | "light" | "dark";

interface ThemeToggleProps {
  value: ThemeMode;
  onChange: (value: ThemeMode) => void;
  className?: string;
}

const OPTIONS: Array<{ value: ThemeMode; label: string; icon: React.ComponentType<{ className?: string }> }> = [
  { value: "system", label: "System", icon: Laptop2 },
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
];

export function ThemeToggle({ value, onChange, className }: ThemeToggleProps) {
  return (
    <div className={cn("theme-toggle", className)} role="group" aria-label="Theme mode">
      {OPTIONS.map((option) => {
        const Icon = option.icon;
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            className={cn("theme-toggle__option", active ? "theme-toggle__option--active" : "")}
            aria-pressed={active}
            onClick={() => onChange(option.value)}
            title={`Use ${option.label.toLowerCase()} theme`}
          >
            <Icon className="h-3.5 w-3.5" />
            <span>{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}
