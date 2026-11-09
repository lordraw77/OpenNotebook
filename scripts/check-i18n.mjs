#!/usr/bin/env node
// Checks the Italian UI dictionary (frontend/src/app/i18n/it.ts) against the texts marked for translation:
// `'English text' | t` in templates and `t('English text')` in code. Fails on missing translations and
// reports unused entries.   node scripts/check-i18n.mjs
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const root = new URL('../frontend/src/app/', import.meta.url).pathname;
const files = [];
(function walk(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path);
    else if (/\.(ts|html)$/.test(name) && !name.endsWith('.spec.ts') && !path.includes('/i18n/') && !path.endsWith('core/i18n.ts')) files.push(path);
  }
})(root);

const unescape = (s) => s.replace(/\\(.)/g, '$1');
const used = new Map();
const patterns = [
  /'((?:[^'\\\n]|\\.)+)'\s*\|\s*t\b/g, // template: 'text' | t
  /(?<![\w.])(?:t|i18nKey)\(\s*'((?:[^'\\\n]|\\.)+)'/g, // code: t('text'), i18nKey('text')
];
for (const file of files) {
  const text = readFileSync(file, 'utf8');
  for (const re of patterns) {
    for (const m of text.matchAll(re)) used.set(unescape(m[1]), file.slice(root.length));
  }
}

const source = readFileSync(join(root, 'i18n/it.ts'), 'utf8');
const keys = new Set();
for (const m of source.matchAll(/^\s*'((?:[^'\\]|\\.)+)'\s*:/gm)) keys.add(unescape(m[1]));
for (const m of source.matchAll(/^\s*"((?:[^"\\]|\\.)+)"\s*:/gm)) keys.add(unescape(m[1]));
for (const m of source.matchAll(/^\s*([A-Za-z_$][\w$]*)\s*:/gm)) keys.add(m[1]); // unquoted (prettier)

const missing = [...used].filter(([k]) => !keys.has(k));
const unused = [...keys].filter((k) => !used.has(k));
for (const [k, file] of missing) console.log(`missing  ${file}: ${k}`);
for (const k of unused) console.log(`unused   ${k}`);
console.log(`${used.size} marked texts, ${keys.size} translations, ${missing.length} missing, ${unused.length} unused`);
process.exit(missing.length ? 1 : 0);
