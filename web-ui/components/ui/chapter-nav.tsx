"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

interface ChapterItem {
  slug: string;
  title: string;
}

interface ChapterNavProps {
  items: ChapterItem[];
}

export function ChapterNav({ items }: ChapterNavProps) {
  const [activeSlug, setActiveSlug] = React.useState<string>(items[0]?.slug ?? "");

  React.useEffect(() => {
    if (!items.length) {
      return;
    }
    const nodes = items
      .map((item) => document.getElementById(item.slug))
      .filter((node): node is HTMLElement => Boolean(node));
    if (!nodes.length) {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
        if (!visible.length) {
          return;
        }
        setActiveSlug(visible[0].target.id);
      },
      {
        root: null,
        rootMargin: "-20% 0px -65% 0px",
        threshold: [0.15, 0.3, 0.6],
      },
    );

    for (const node of nodes) {
      observer.observe(node);
    }
    return () => observer.disconnect();
  }, [items]);

  if (items.length === 0) {
    return null;
  }

  return (
    <aside className="chapter-nav">
      <p className="chapter-nav__title">Chapters</p>
      <nav className="chapter-nav__links">
        {items.map((item) => (
          <a
            key={item.slug}
            href={`#${item.slug}`}
            className={cn("chapter-nav__link", activeSlug === item.slug ? "chapter-nav__link--active" : "")}
            aria-current={activeSlug === item.slug ? "true" : undefined}
          >
            {item.title}
          </a>
        ))}
      </nav>
    </aside>
  );
}
