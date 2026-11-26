"use client";

import clsx from "clsx";
import { Check, Copy } from "lucide-react";
import { useEffect, useState } from "react";

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // navigator.clipboard is unavailable on plain HTTP.
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    (document.querySelector("dialog[open]") ?? document.body).appendChild(area);
    area.select();
    const done = document.execCommand("copy");
    area.remove();
    return done;
  }
}

type CopyButtonProps = {
  text: string;
  ariaLabel: string;
  className?: string;
  children: React.ReactNode;
};

export function CopyButton({ text, ariaLabel, className, children }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1600);
    return () => clearTimeout(timer);
  }, [copied]);

  const Icon = copied ? Check : Copy;
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      title={ariaLabel}
      onClick={async () => setCopied(await copyText(text))}
      className={clsx("inline-flex items-center gap-1.5", className)}
    >
      {children}
      <Icon size={14} aria-hidden />
      <span aria-live="polite" className="sr-only">
        {copied ? "Đã sao chép" : ""}
      </span>
    </button>
  );
}
