import { Component, inject } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatToolbarModule } from '@angular/material/toolbar';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { AuthService } from '../core/auth.service';

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
  ],
  template: `
    <mat-toolbar class="topbar">
      <span class="brand"><mat-icon>auto_stories</mat-icon> OpenNotebook</span>
      <nav>
        <a mat-button routerLink="/workbench" routerLinkActive="active"
          ><mat-icon>forum</mat-icon> Workbench</a
        >
        <a mat-button routerLink="/upload" routerLinkActive="active"
          ><mat-icon>upload_file</mat-icon> Upload</a
        >
        <a mat-button routerLink="/status" routerLinkActive="active"
          ><mat-icon>monitor_heart</mat-icon> RAG Status</a
        >
        <a mat-button routerLink="/settings" routerLinkActive="active"
          ><mat-icon>settings</mat-icon> Settings</a
        >
      </nav>
      <span class="spacer"></span>
      <button mat-button [matMenuTriggerFor]="userMenu" aria-label="Account menu">
        <mat-icon>account_circle</mat-icon> {{ auth.user()?.display_name }}
      </button>
      <mat-menu #userMenu="matMenu">
        <div class="menu-email">{{ auth.user()?.email }}</div>
        <button mat-menu-item (click)="auth.logout()"><mat-icon>logout</mat-icon> Sign out</button>
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
      gap: 8px;
      border-bottom: 1px solid var(--mat-sys-outline-variant);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 8px;
      font-weight: 500;
      margin-right: 16px;
    }
    nav {
      display: flex;
      gap: 4px;
      overflow-x: auto;
    }
    nav a.active {
      background: var(--mat-sys-secondary-container);
      color: var(--mat-sys-on-secondary-container);
    }
    .spacer {
      flex: 1;
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
    @media (max-width: 800px) {
      nav a {
        min-width: 0;
      }
      .brand span {
        display: none;
      }
    }
  `,
})
export class ShellComponent {
  protected readonly auth = inject(AuthService);
}
