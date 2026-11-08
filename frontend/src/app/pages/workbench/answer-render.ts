/**
 * Minimal Markdown for chat answers, rendered from typed segments (no innerHTML, nothing to sanitize).
 * Supports headings, paragraphs, bullet and numbered lists, fenced code, **bold**, *italic*, `code`,
 * and citation markers [S3], which become clickable chips.
 */

export type Inline =
  | { kind: 'text'; text: string }
  | { kind: 'strong'; text: string }
  | { kind: 'em'; text: string }
  | { kind: 'code'; text: string }
  | { kind: 'cite'; n: number };

export type Block =
  | { kind: 'heading'; level: number; inlines: Inline[] }
  | { kind: 'paragraph'; inlines: Inline[] }
  | { kind: 'list'; ordered: boolean; items: Inline[][] }
  | { kind: 'code'; text: string };

const INLINE = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\[S\d+\]|(?<![\w*])\*[^*\s][^*\n]*\*(?!\w))/g;
const BULLET = /^\s*[-*+]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const HEADING = /^(#{1,6})\s+(.*)$/;

export function parseInline(text: string): Inline[] {
  const out: Inline[] = [];
  let last = 0;
  for (const m of text.matchAll(INLINE)) {
    if (m.index > last) out.push({ kind: 'text', text: text.slice(last, m.index) });
    const tok = m[0];
    if (tok.startsWith('**')) out.push({ kind: 'strong', text: tok.slice(2, -2) });
    else if (tok.startsWith('`')) out.push({ kind: 'code', text: tok.slice(1, -1) });
    else if (tok.startsWith('[S')) out.push({ kind: 'cite', n: Number(tok.slice(2, -1)) });
    else out.push({ kind: 'em', text: tok.slice(1, -1) });
    last = m.index + tok.length;
  }
  if (last < text.length) out.push({ kind: 'text', text: text.slice(last) });
  return out;
}

export function parseAnswer(content: string): Block[] {
  const blocks: Block[] = [];
  const lines = content.replace(/\r\n/g, '\n').split('\n');
  let para: string[] = [];
  let list: { ordered: boolean; items: Inline[][] } | null = null;

  const flushPara = () => {
    if (para.length) blocks.push({ kind: 'paragraph', inlines: parseInline(para.join(' ')) });
    para = [];
  };
  const flushList = () => {
    if (list) blocks.push({ kind: 'list', ...list });
    list = null;
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.trim().startsWith('```')) {
      flushPara();
      flushList();
      const code: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')) code.push(lines[i++]);
      blocks.push({ kind: 'code', text: code.join('\n') });
      continue;
    }
    const heading = HEADING.exec(line);
    const bullet = BULLET.exec(line);
    const numbered = NUMBERED.exec(line);
    if (!line.trim()) {
      flushPara();
      flushList();
    } else if (heading) {
      flushPara();
      flushList();
      blocks.push({
        kind: 'heading',
        level: heading[1].length,
        inlines: parseInline(heading[2]),
      });
    } else if (bullet || numbered) {
      flushPara();
      const ordered = !!numbered && !bullet;
      if (list && list.ordered !== ordered) flushList();
      list ??= { ordered, items: [] };
      list.items.push(parseInline((bullet ?? numbered)![1]));
    } else if (list && /^\s{2,}/.test(line)) {
      // continuation of the previous list item
      list.items[list.items.length - 1].push(...parseInline(' ' + line.trim()));
    } else {
      flushList();
      para.push(line.trim());
    }
  }
  flushPara();
  flushList();
  return blocks;
}
