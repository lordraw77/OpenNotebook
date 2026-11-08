import { Injectable, signal } from '@angular/core';

/** Color scheme chosen by the user; `system` follows the OS preference. */
export type ThemeMode = 'system' | 'light' | 'dark';

const STORAGE_KEY = 'on.theme';
const MODES: readonly ThemeMode[] = ['system', 'light', 'dark'];

/** Reads the stored mode; storage may be unavailable (private windows, blocked site data). */
export function storedThemeMode(): ThemeMode {
  try {
    const value = localStorage.getItem(STORAGE_KEY) as ThemeMode | null;
    return value && MODES.includes(value) ? value : 'system';
  } catch {
    return 'system';
  }
}

/** Applies a mode to <html>: the Material tokens use light-dark(), driven by color-scheme. */
export function applyThemeMode(mode: ThemeMode): void {
  const root = document.documentElement;
  if (mode === 'system') {
    delete root.dataset['theme'];
  } else {
    root.dataset['theme'] = mode;
  }
}

@Injectable({ providedIn: 'root' })
export class ThemeService {
  readonly mode = signal<ThemeMode>(storedThemeMode());

  set(mode: ThemeMode): void {
    this.mode.set(mode);
    applyThemeMode(mode);
    try {
      localStorage.setItem(STORAGE_KEY, mode);
    } catch {
      // Preference is per browser only; ignore storage failures.
    }
  }

  icon(): string {
    return { system: 'brightness_auto', light: 'light_mode', dark: 'dark_mode' }[this.mode()];
  }
}
