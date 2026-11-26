"use client";

import { Moon, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";

import { IconButton } from "@/components/ui/Button";

const DARK_QUERY = "(prefers-color-scheme: dark)";

function isDark() {
  const chosen = document.documentElement.dataset.theme;
  return chosen ? chosen === "dark" : window.matchMedia(DARK_QUERY).matches;
}

function subscribe(notify: () => void) {
  const media = window.matchMedia(DARK_QUERY);
  media.addEventListener("change", notify);
  const observer = new MutationObserver(notify);
  observer.observe(document.documentElement, { attributeFilter: ["data-theme"] });
  return () => {
    media.removeEventListener("change", notify);
    observer.disconnect();
  };
}

export function ThemeToggle() {
  const dark = useSyncExternalStore(subscribe, isDark, () => false);
  const Icon = dark ? Sun : Moon;
  return (
    <IconButton
      label={dark ? "Chuyển sang giao diện sáng" : "Chuyển sang giao diện tối"}
      onClick={() => {
        const theme = dark ? "light" : "dark";
        document.documentElement.dataset.theme = theme;
        try {
          localStorage.setItem("traffic-law:theme", theme);
        } catch {
          // the choice then lasts for this page only
        }
      }}
    >
      <Icon size={18} aria-hidden />
    </IconButton>
  );
}
