import { parseAnswer, parseInline } from './answer-render';

describe('answer renderer', () => {
  it('turns citation markers into chips and keeps inline formatting', () => {
    expect(parseInline('Hold **reset** for `10 s` [S2][S3].')).toEqual([
      { kind: 'text', text: 'Hold ' },
      { kind: 'strong', text: 'reset' },
      { kind: 'text', text: ' for ' },
      { kind: 'code', text: '10 s' },
      { kind: 'text', text: ' ' },
      { kind: 'cite', n: 2 },
      { kind: 'cite', n: 3 },
      { kind: 'text', text: '.' },
    ]);
  });

  it('parses headings, lists, paragraphs and code blocks', () => {
    const blocks = parseAnswer(
      '## Steps\n\n1. Power off [S1].\n2. Hold *reset*.\n\nThen wait.\n```\nreboot\n```\n- a\n- b',
    );
    expect(blocks.map((b) => b.kind)).toEqual(['heading', 'list', 'paragraph', 'code', 'list']);
    const ordered = blocks[1] as { ordered: boolean; items: unknown[] };
    expect(ordered.ordered).toBe(true);
    expect(ordered.items.length).toBe(2);
    expect(blocks[3]).toEqual({ kind: 'code', text: 'reboot' });
  });

  it('treats markup as text, never as HTML', () => {
    const [block] = parseAnswer('<img src=x onerror=alert(1)>');
    expect(block).toEqual({
      kind: 'paragraph',
      inlines: [{ kind: 'text', text: '<img src=x onerror=alert(1)>' }],
    });
  });
});
