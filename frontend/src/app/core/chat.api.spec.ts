import { parseSse } from './chat.api';

describe('parseSse', () => {
  it('parses complete events and keeps the partial remainder', () => {
    const { events, rest } = parseSse(
      'event: token\ndata: {"text":"Hel"}\n\nevent: token\ndata: {"text":"lo"}\n\nevent: do',
    );
    expect(events).toEqual([
      { event: 'token', data: { text: 'Hel' } },
      { event: 'token', data: { text: 'lo' } },
    ]);
    expect(rest).toBe('event: do');
  });
});
