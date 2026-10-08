import clsx from "clsx";
import { useEffect, useState } from "react";
import { applyTheme, initialTheme, onThemeChange, setTheme as switchTheme, type Theme } from "../lib/theme";
import { Moon, Sun } from "./icons";

/** Light / dark toggle: a labelled two-state switch (the label states the state; the icon is reinforcement). Compact = icon button with a tooltip. */
export function ThemeSwitch({ compact = false }: { compact?: boolean }) {
  const [theme, setTheme] = useState<Theme>(() => (typeof window === "undefined" ? "light" : initialTheme()));
  useEffect(() => applyTheme(theme), [theme]);
  useEffect(() => onThemeChange(setTheme), []);
  const next: Theme = theme === "light" ? "dark" : "light";
  return (
    <button
      type="button"
      className={clsx("btn", compact ? "btn-icon" : "btn-ghost w-full justify-start")}
      aria-label={`Switch to ${next} theme`}
      data-tip={compact ? `Switch to ${next} theme` : undefined}
      title={compact ? undefined : `Switch to ${next} theme`}
      onClick={() => {
        setTheme(next);
        switchTheme(next);
      }}
    >
      {theme === "light" ? <Sun size={16} /> : <Moon size={16} />}
      {!compact && <span>{theme === "light" ? "Light theme" : "Dark theme"}</span>}
    </button>
  );
}
