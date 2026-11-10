import { BreakpointObserver } from '@angular/cdk/layout';
import { Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { map } from 'rxjs';

import { AuthService } from '../core/auth.service';
import { LANGS, Lang, TranslatePipe, currentLang, setLang, t } from '../core/i18n';
import { ThemeMode, ThemeService } from '../core/theme.service';

interface NavItem {
  link: string;
  icon: string;
  label: string;
}

@Component({
  selector: 'app-shell',
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    MatToolbarModule,
    MatButtonModule,
    MatIconModule,
    MatMenuModule,
    MatTooltipModule,
    TranslatePipe,
  ],
  template: `
    <mat-toolbar class="topbar">
      <a class="brand" routerLink="/workbench" [attr.aria-label]="'OpenNotebook home' | t">
        <span class="logo"><mat-icon>auto_stories</mat-icon></span>
        @if (!compact()) {
          <span class="gradient-text">OpenNotebook</span>
        }
      </a>
      <nav [attr.aria-label]="'Main' | t">
        @for (item of nav; track item.link) {
          <a
            class="nav-link"
            [routerLink]="item.link"
            routerLinkActive="active"
            #rla="routerLinkActive"
            [attr.aria-current]="rla.isActive ? 'page' : null"
            [attr.aria-label]="item.label"
            [matTooltip]="item.label"
            [matTooltipDisabled]="!compact()"
          >
            <mat-icon>{{ item.icon }}</mat-icon>
            @if (!compact()) {
              <span>{{ item.label }}</span>
            }
          </a>
        }
      </nav>
      <span class="spacer"></span>
      <button
        mat-icon-button
        [matMenuTriggerFor]="themeMenu"
        [matTooltip]="'Theme' | t"
        [attr.aria-label]="'Choose theme' | t"
      >
        <mat-icon>{{ theme.icon() }}</mat-icon>
      </button>
      <mat-menu #themeMenu="matMenu">
        @for (item of themes; track item.mode) {
          <button mat-menu-item (click)="theme.set(item.mode)">
            <mat-icon>{{ item.icon }}</mat-icon>
            <span>{{ item.label }}</span>
            @if (theme.mode() === item.mode) {
              <mat-icon class="check">check</mat-icon>
            }
          </button>
        }
      </mat-menu>
      <button
        mat-icon-button
        [matMenuTriggerFor]="langMenu"
        [matTooltip]="'Language' | t"
        [attr.aria-label]="'Choose language' | t"
      >
        <mat-icon>translate</mat-icon>
      </button>
      <mat-menu #langMenu="matMenu">
        @for (item of langs; track item.lang) {
          <button mat-menu-item [attr.lang]="item.lang" (click)="chooseLang(item.lang)">
            <span>{{ item.label }}</span>
            @if (lang === item.lang) {
              <mat-icon class="check">check</mat-icon>
            }
          </button>
        }
      </mat-menu>
      <button class="account" [matMenuTriggerFor]="userMenu" [attr.aria-label]="'Account menu' | t">
        <span class="avatar">{{ initials() }}</span>
        @if (!compact()) {
          <span class="account-name">{{ auth.user()?.display_name }}</span>
        }
      </button>
      <mat-menu #userMenu="matMenu">
        <div class="menu-email">{{ auth.user()?.email }}</div>
        <button mat-menu-item (click)="auth.logout()">
          <mat-icon>logout</mat-icon> {{ 'Sign out' | t }}
        </button>
      </mat-menu>
    </mat-toolbar>
    <main class="content"><router-outlet /></main>
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      height: 100vh;
    }
    .topbar {
      position: relative;
      gap: 8px;
      height: 60px;
      padding: 0 12px;
      background: var(--on-topbar-bg);
      backdrop-filter: blur(12px);
      overflow: hidden;
      flex-shrink: 0;
    }
    .topbar::after {
      content: '';
      position: absolute;
      inset: auto 0 0 0;
      height: 2px;
      background: var(--on-gradient);
      opacity: 0.85;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      font: var(--mat-sys-title-large);
      font-weight: 700;
      letter-spacing: -0.01em;
      text-decoration: none;
      margin-right: 12px;
      flex-shrink: 0;
    }
    .logo {
      display: grid;
      place-items: center;
      width: 36px;
      height: 36px;
      border-radius: 10px;
      background: var(--on-gradient);
      color: #fff;
      box-shadow: 0 4px 14px var(--on-glow);
    }
    nav {
      display: flex;
      align-items: center;
      gap: 4px;
      min-width: 0;
      flex-shrink: 1;
    }
    .nav-link {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      height: 40px;
      padding: 0 14px;
      border-radius: 20px;
      color: var(--mat-sys-on-surface-variant);
      font: var(--mat-sys-label-large);
      text-decoration: none;
      white-space: nowrap;
      transition:
        background-color 150ms,
        color 150ms;
    }
    .nav-link:hover {
      background: color-mix(in srgb, var(--mat-sys-primary) 10%, transparent);
      color: var(--mat-sys-on-surface);
    }
    .nav-link:focus-visible {
      outline: 2px solid var(--mat-sys-primary);
      outline-offset: 2px;
    }
    .nav-link.active {
      background: var(--mat-sys-primary-container);
      color: var(--mat-sys-on-primary-container);
    }
    .nav-link mat-icon {
      font-size: 20px;
      width: 20px;
      height: 20px;
    }
    .spacer {
      flex: 1;
    }
    .account {
      display: flex;
      align-items: center;
      gap: 8px;
      height: 40px;
      padding: 0 12px 0 4px;
      border: 1px solid var(--mat-sys-outline-variant);
      border-radius: 20px;
      background: var(--mat-sys-surface-container-low);
      color: var(--mat-sys-on-surface);
      font: var(--mat-sys-label-large);
      cursor: pointer;
      flex-shrink: 0;
    }
    .account:focus-visible {
      outline: 2px solid var(--mat-sys-primary);
      outline-offset: 2px;
    }
    .avatar {
      display: grid;
      place-items: center;
      width: 32px;
      height: 32px;
      border-radius: 50%;
      background: var(--on-gradient);
      color: #fff;
      font-size: 13px;
      font-weight: 600;
    }
    .account-name {
      max-width: 160px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .content {
      flex: 1;
      min-height: 0;
      overflow: auto;
    }
    .menu-email {
      padding: 8px 16px;
      color: var(--mat-sys-on-surface-variant);
      font-size: 13px;
    }
    .check {
      margin-left: 16px;
      color: var(--mat-sys-primary);
    }
    @media (max-width: 1099px) {
      .nav-link {
        padding: 0 10px;
      }
      .account {
        padding: 0 4px;
      }
    }
  `,
})
export class ShellComponent {
  protected readonly auth = inject(AuthService);
  protected readonly theme = inject(ThemeService);

  /** Below 1100 px the navigation shows icons only (with tooltips): no scrolling header. */
  protected readonly compact = toSignal(
    inject(BreakpointObserver)
      .observe('(max-width: 1099px)')
      .pipe(map((state) => state.matches)),
    { initialValue: false },
  );

  protected readonly nav: NavItem[] = [
    { link: '/workbench', icon: 'forum', label: t('Workbench') },
    { link: '/history', icon: 'history', label: t('History') },
    { link: '/upload', icon: 'upload_file', label: t('Upload') },
    { link: '/wiki', icon: 'hub', label: t('Wiki') },
    { link: '/status', icon: 'monitor_heart', label: t('RAG Status') },
    { link: '/settings', icon: 'settings', label: t('Settings') },
    { link: '/guide', icon: 'menu_book', label: t('Guide') },
  ];

  /** Language names are shown in their own language. */
  protected readonly langs = LANGS;
  protected readonly lang = currentLang();

  protected chooseLang(lang: Lang): void {
    if (lang !== this.lang) setLang(lang);
  }

  protected readonly themes: { mode: ThemeMode; icon: string; label: string }[] = [
    { mode: 'system', icon: 'brightness_auto', label: t('System') },
    { mode: 'light', icon: 'light_mode', label: t('Light') },
    { mode: 'dark', icon: 'dark_mode', label: t('Dark') },
  ];

  protected readonly initials = computed(() => {
    const name = this.auth.user()?.display_name ?? this.auth.user()?.email ?? '?';
    return (
      name
        .split(/[\s@._-]+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((part) => part[0]!.toUpperCase())
        .join('') || '?'
    );
  });
}
