import { Pipe, PipeTransform } from '@angular/core';

import { IT } from '../i18n/it';

/**
 * Runtime UI translation (NFR-06). Keys are the English texts, so English needs no dictionary and a missing
 * translation falls back to English. The language is chosen at startup (stored preference, else the browser
 * language); switching reloads the page so dates, numbers and every string follow the new locale.
 * Placeholders: `t('Deleted {name}', { name })`. `scripts/check-i18n.mjs` checks that every marked string
 * has an Italian translation.
 */
export type Lang = 'en' | 'it';

export const LANGS: { lang: Lang; label: string }[] = [
  { lang: 'en', label: 'English' },
  { lang: 'it', label: 'Italiano' },
];

const STORAGE_KEY = 'on.lang';
const DICTIONARIES: Record<Lang, Readonly<Record<string, string>>> = { en: {}, it: IT };

let current: Lang = 'en';

export function storedLang(): Lang {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (value === 'en' || value === 'it') return value;
  } catch {
    // storage unavailable: fall back to the browser language
  }
  return navigator.language?.toLowerCase().startsWith('it') ? 'it' : 'en';
}

/** Called once before bootstrap. */
export function initLang(lang: Lang = storedLang()): Lang {
  current = lang;
  document.documentElement.lang = lang;
  return lang;
}

export function currentLang(): Lang {
  return current;
}

/** Angular locale id for dates and numbers. */
export function localeId(lang: Lang = current): string {
  return lang === 'it' ? 'it' : 'en-US';
}

export function setLang(lang: Lang): void {
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    // preference cannot be stored: it applies to this page load only
  }
  location.reload();
}

/** Marks a constant English text for translation without translating it (translate at use with `t`). */
export function i18nKey(text: string): string {
  return text;
}

/** Translates an English UI text; `{name}` placeholders are replaced by `params`. */
export function t(
  text: string,
  params?: Record<string, string | number | null | undefined>,
): string {
  const translated = DICTIONARIES[current][text] ?? text;
  if (!params) return translated;
  return translated.replace(/\{(\w+)\}/g, (match, key: string) =>
    params[key] === undefined || params[key] === null ? match : String(params[key]),
  );
}

@Pipe({ name: 't' })
export class TranslatePipe implements PipeTransform {
  transform(text: string, params?: Record<string, string | number | null | undefined>): string {
    return t(text, params);
  }
}
