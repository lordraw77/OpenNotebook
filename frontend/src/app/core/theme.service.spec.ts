import { TestBed } from '@angular/core/testing';

import { ThemeService, storedThemeMode } from './theme.service';

describe('ThemeService', () => {
  afterEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset['theme'];
  });

  it('defaults to the system scheme', () => {
    expect(storedThemeMode()).toBe('system');
    expect(TestBed.inject(ThemeService).mode()).toBe('system');
  });

  it('forces a scheme on <html> and remembers it', () => {
    const theme = TestBed.inject(ThemeService);
    theme.set('light');
    expect(document.documentElement.dataset['theme']).toBe('light');
    expect(storedThemeMode()).toBe('light');
    theme.set('system');
    expect(document.documentElement.dataset['theme']).toBeUndefined();
  });

  it('ignores unknown stored values', () => {
    localStorage.setItem('on.theme', 'neon');
    expect(storedThemeMode()).toBe('system');
  });
});
