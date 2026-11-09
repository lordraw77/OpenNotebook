import { IT } from '../i18n/it';
import { TranslatePipe, currentLang, initLang, localeId, t } from './i18n';

describe('i18n', () => {
  afterEach(() => initLang('en'));

  it('falls back to English and fills placeholders', () => {
    initLang('en');
    expect(t('Sign out')).toBe('Sign out');
    expect(t('Delete note “{title}”?', { title: 'Plan' })).toBe('Delete note “Plan”?');
    expect(t('Not a known text {x}', {})).toBe('Not a known text {x}');
    expect(localeId()).toBe('en-US');
  });

  it('translates to Italian, including placeholders and the pipe', () => {
    initLang('it');
    expect(currentLang()).toBe('it');
    expect(document.documentElement.lang).toBe('it');
    expect(t('Sign out')).toBe('Esci');
    expect(t('{n} sources queued', { n: 3 })).toBe('3 fonti in coda');
    expect(new TranslatePipe().transform('Delete note “{title}”?', { title: 'Piano' })).toBe(
      'Eliminare la nota “Piano”?',
    );
    expect(localeId()).toBe('it');
  });

  it('keeps every placeholder of the English text in the Italian one', () => {
    for (const [en, it] of Object.entries(IT)) {
      const names = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort().join();
      expect(names(it), en).toBe(names(en));
    }
  });
});
