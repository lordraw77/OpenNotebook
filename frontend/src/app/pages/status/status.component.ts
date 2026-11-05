import { DecimalPipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';

import { ComponentStatus } from '../../core/api.models';
import { ApiService, errorMessage } from '../../core/api.service';

@Component({
  selector: 'app-status',
  imports: [MatCardModule, MatIconModule, MatButtonModule, DecimalPipe],
  template: `
    <div class="page">
      <div class="row">
        <h1>RAG Status</h1>
        <span class="spacer"></span>
        <span class="muted">Version {{ version() }}</span>
        <button mat-stroked-button (click)="load()"><mat-icon>refresh</mat-icon> Refresh</button>
      </div>
      @if (error()) {
        <p class="error-text">{{ error() }}</p>
      }
      <h2 class="section">Services</h2>
      <div class="grid">
        @for (c of components(); track c.name) {
          <mat-card appearance="outlined" class="svc" [class.down]="!c.ok">
            <mat-icon>{{ c.ok ? 'check_circle' : 'error' }}</mat-icon>
            <div>
              <div class="name">{{ c.name }}</div>
              <div class="muted">{{ c.ok ? (c.latency_ms | number) + ' ms' : c.error }}</div>
            </div>
          </mat-card>
        }
      </div>
      <h2 class="section">Ingestion</h2>
      <p class="muted">
        Queues, per-source status, chunk counts and re-index actions arrive with ingestion in
        milestone M1.
      </p>
    </div>
  `,
  styles: `
    .spacer {
      flex: 1;
    }
    .section {
      font: var(--mat-sys-title-medium);
      margin: 24px 0 8px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
      gap: 12px;
    }
    .svc {
      display: flex;
      flex-direction: row;
      gap: 12px;
      align-items: center;
      padding: 16px;
    }
    .svc mat-icon {
      color: var(--mat-sys-primary);
    }
    .svc.down mat-icon {
      color: var(--mat-sys-error);
    }
    .name {
      font-weight: 500;
      text-transform: capitalize;
    }
  `,
})
export class StatusComponent {
  private readonly api = inject(ApiService);
  readonly components = signal<ComponentStatus[]>([]);
  readonly version = signal('');
  readonly error = signal<string | null>(null);

  constructor() {
    void this.load();
  }

  async load(): Promise<void> {
    this.error.set(null);
    try {
      const res = await this.api.status();
      this.components.set(res.components);
      this.version.set(res.version);
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }
}
