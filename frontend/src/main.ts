import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { App } from './app/app';
import { initLang } from './app/core/i18n';
import { applyThemeMode, storedThemeMode } from './app/core/theme.service';

// Apply the stored color scheme and language before the first render (no inline script: strict CSP).
applyThemeMode(storedThemeMode());
initLang();

bootstrapApplication(App, appConfig).catch((err) => console.error(err));
