import { useCallback, useEffect, useState } from 'react';

export type Theme = 'light' | 'dark';

const KEY = 'optiflow-theme';

function readStored(): Theme {
  try {
    const v = localStorage.getItem(KEY);
    if (v === 'dark' || v === 'light') return v;
  } catch {
    /* storage unavailable (private mode, blocked cookies) */
  }
  return 'light';
}

/** Light is the product default; dark is opt-in and persists per browser. */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(readStored);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute('content', theme === 'dark' ? '#0E0F10' : '#FAFAF9');
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);

  const toggle = useCallback(() => setTheme((t) => (t === 'dark' ? 'light' : 'dark')), []);

  return { theme, setTheme, toggle };
}
