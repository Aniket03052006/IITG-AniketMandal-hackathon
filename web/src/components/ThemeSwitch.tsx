import clsx from "clsx";
import { useEffect, useState } from "react";
import { applyTheme, initialTheme, storeTheme, type Theme } from "../lib/theme";
import { Moon, Sun } from "./icons";

/** Light / dark toggle: a labelled two-state switch (the label states the state; the icon is reinforcement). */
export function ThemeSwitch({ compact = false }: { compact?: boolean }) {
  const [theme, setTheme] = useState<Theme>(() => (typeof window === "undefined" ? "light" : initialTheme()));
  useEffect(() => applyTheme(theme), [theme]);
  const next: Theme = theme === "light" ? "dark" : "light";
  return (
    <button
      type="button"
      className={clsx("btn btn-ghost", compact ? "px-2" : "w-full justify-start")}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
      onClick={() => {
        setTheme(next);
        storeTheme(next);
      }}
    >
      {theme === "light" ? <Sun size={15} /> : <Moon size={15} />}
      {!compact && <span>{theme === "light" ? "Light theme" : "Dark theme"}</span>}
    </button>
  );
}
