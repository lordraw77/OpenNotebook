import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, DestroyRef, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';

import { ComponentStatus, TreeNodeDto } from '../../core/api.models';
import { ApiService, errorMessage } from '../../core/api.service';
import { IngestionStatus, SourcesApi } from '../../core/sources.api';

@Component({
  selector: 'app-status',
  imports: [
    MatCardModule,
    MatIconModule,
    MatButtonModule,
    MatTableModule,
    MatTooltipModule,
    DecimalPipe,
    DatePipe,
  ],
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

      @if (ingestion(); as ing) {
        <h2 class="section">Sources by status</h2>
        <div class="grid">
          @for (s of statuses; track s) {
            <mat-card
              appearance="outlined"
              class="svc"
              [class.down]="s === 'failed' && ing.by_status[s] > 0"
            >
              <div>
                <div class="count">{{ ing.by_status[s] }}</div>
                <div class="muted name">{{ s }}</div>
              </div>
            </mat-card>
          }
        </div>
        <p class="muted">
          Queues:
          @if (ing.queues) {
            @for (q of queueNames(ing); track q) {
              {{ q }} {{ ing.queues[q] }}{{ $last ? '' : ' · ' }}
            }
          } @else {
            unavailable
          }
        </p>

        <h2 class="section">Index by project</h2>
        <div class="table-wrap">
          <table mat-table [dataSource]="ing.projects">
            <ng-container matColumnDef="project">
              <th mat-header-cell *matHeaderCellDef>Project</th>
              <td mat-cell *matCellDef="let p">{{ p.project_name }}</td>
            </ng-container>
            <ng-container matColumnDef="model">
              <th mat-header-cell *matHeaderCellDef>Embedding model</th>
              <td mat-cell *matCellDef="let p">
                {{ p.embedding_model ?? 'not configured' }}
                @if (p.embedding_source === 'project') {
                  <span class="cap">project override</span>
                }
                @if (p.switch_pending) {
                  <div class="muted small-note">
                    <mat-icon inline>sync</mat-icon> searches still served by
                    <strong>{{ p.serving_model }}</strong> until every source is re-indexed
                  </div>
                }
              </td>
            </ng-container>
            <ng-container matColumnDef="sources">
              <th mat-header-cell *matHeaderCellDef>Sources</th>
              <td mat-cell *matCellDef="let p">{{ p.sources }}</td>
            </ng-container>
            <ng-container matColumnDef="chunks">
              <th mat-header-cell *matHeaderCellDef>Chunks</th>
              <td mat-cell *matCellDef="let p">{{ p.chunks | number }}</td>
            </ng-container>
            <ng-container matColumnDef="stale">
              <th mat-header-cell *matHeaderCellDef>Needs re-index</th>
              <td mat-cell *matCellDef="let p">
                @if (p.stale_sources) {
                  <span
                    class="error-text"
                    matTooltip="Indexed with a different embedding model than the current one"
                    >{{ p.stale_sources }}</span
                  >
                } @else {
                  0
                }
              </td>
            </ng-container>
            <ng-container matColumnDef="actions">
              <th mat-header-cell *matHeaderCellDef></th>
              <td mat-cell *matCellDef="let p">
                @if (isOwner(p.project_id)) {
                  <button
                    mat-button
                    (click)="reindexProject(p.project_id, p.project_name)"
                    [disabled]="!p.sources"
                  >
                    <mat-icon>refresh</mat-icon> Re-index
                  </button>
                  <button
                    mat-button
                    (click)="rebuildGraph(p.project_id, p.project_name)"
                    [disabled]="!p.sources"
                  >
                    <mat-icon>hub</mat-icon> Rebuild graph
                  </button>
                }
              </td>
            </ng-container>
            <tr mat-header-row *matHeaderRowDef="projectColumns"></tr>
            <tr mat-row *matRowDef="let p; columns: projectColumns"></tr>
            <tr class="mat-row" *matNoDataRow>
              <td class="mat-cell muted" [attr.colspan]="projectColumns.length">No projects.</td>
            </tr>
          </table>
        </div>

        @if (ing.failed.length) {
          <h2 class="section">Failed sources</h2>
          <ul class="list">
            @for (f of ing.failed; track f.id) {
              <li>
                <mat-icon class="bad">error</mat-icon>
                <strong>{{ f.title }}</strong>
                <span class="error-text">{{ f.error?.message }}</span>
                <span class="spacer"></span>
                <button mat-button (click)="retry(f.id)">Retry</button>
              </li>
            }
          </ul>
        }

        <h2 class="section">Recent jobs</h2>
        <div class="table-wrap">
          <table mat-table [dataSource]="ing.recent_jobs">
            <ng-container matColumnDef="when">
              <th mat-header-cell *matHeaderCellDef>Started</th>
              <td mat-cell *matCellDef="let j">{{ j.created_at | date: 'short' }}</td>
            </ng-container>
            <ng-container matColumnDef="reason">
              <th mat-header-cell *matHeaderCellDef>Reason</th>
              <td mat-cell *matCellDef="let j">{{ j.reason }}</td>
            </ng-container>
            <ng-container matColumnDef="status">
              <th mat-header-cell *matHeaderCellDef>Result</th>
              <td mat-cell *matCellDef="let j" [matTooltip]="j.error ?? ''">
                {{ j.status }}{{ j.attempts > 1 ? ' (attempt ' + j.attempts + ')' : '' }}
              </td>
            </ng-container>
            <ng-container matColumnDef="model">
              <th mat-header-cell *matHeaderCellDef>Embedding model</th>
              <td mat-cell *matCellDef="let j">{{ j.provider_model ?? '—' }}</td>
            </ng-container>
            <tr mat-header-row *matHeaderRowDef="jobColumns"></tr>
            <tr mat-row *matRowDef="let j; columns: jobColumns"></tr>
            <tr class="mat-row" *matNoDataRow>
              <td class="mat-cell muted" [attr.colspan]="jobColumns.length">No jobs yet.</td>
            </tr>
          </table>
        </div>
      }
    </div>
  `,
  styles: `
    .small-note {
      font-size: 12px;
      margin-top: 2px;
    }
    .spacer {
      flex: 1;
    }
    .section {
      font: var(--mat-sys-title-medium);
      margin: 24px 0 8px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
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
    .svc.down mat-icon,
    .svc.down .count {
      color: var(--mat-sys-error);
    }
    .name {
      font-weight: 500;
      text-transform: capitalize;
    }
    .count {
      font: var(--mat-sys-headline-small);
    }
    .table-wrap {
      overflow-x: auto;
    }
    table {
      width: 100%;
    }
    .list {
      list-style: none;
      padding: 0;
    }
    .list li {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      padding: 4px 0;
    }
    .bad {
      color: var(--mat-sys-error);
    }
  `,
})
export class StatusComponent {
  private readonly api = inject(ApiService);
  private readonly sourcesApi = inject(SourcesApi);
  private readonly snack = inject(MatSnackBar);

  readonly components = signal<ComponentStatus[]>([]);
  readonly ingestion = signal<IngestionStatus | null>(null);
  private readonly projects = signal<TreeNodeDto[]>([]);
  readonly version = signal('');
  readonly error = signal<string | null>(null);
  readonly statuses = ['queued', 'parsing', 'chunking', 'embedding', 'ready', 'failed'] as const;
  readonly projectColumns = ['project', 'model', 'sources', 'chunks', 'stale', 'actions'];
  readonly jobColumns = ['when', 'reason', 'status', 'model'];

  constructor() {
    void this.load();
    const timer = setInterval(() => void this.loadIngestion(), 5000);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  queueNames(ing: IngestionStatus): string[] {
    return Object.keys(ing.queues ?? {});
  }

  isOwner(projectId: string): boolean {
    return this.projects().find((p) => p.id === projectId)?.role === 'owner';
  }

  async load(): Promise<void> {
    this.error.set(null);
    try {
      const [res, nodes] = await Promise.all([this.api.status(), this.api.nodes()]);
      this.components.set(res.components);
      this.version.set(res.version);
      this.projects.set(nodes.filter((n) => n.kind === 'project'));
      await this.loadIngestion();
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }

  private async loadIngestion(): Promise<void> {
    try {
      this.ingestion.set(await this.sourcesApi.ingestionStatus());
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }

  async reindexProject(id: string, name: string): Promise<void> {
    if (
      !confirm(
        `Re-index every source of “${name}”? This calls the embedding provider for all chunks.`,
      )
    )
      return;
    try {
      const r = await this.sourcesApi.reindexProject(id);
      this.snack.open(`${r.queued} sources queued`, 'Close', { duration: 3000 });
      await this.loadIngestion();
    } catch (err) {
      this.snack.open(errorMessage(err), 'Close', { duration: 5000 });
    }
  }

  async rebuildGraph(id: string, name: string): Promise<void> {
    if (
      !confirm(
        `Re-extract the knowledge graph of “${name}”? Documents are sent again to the graph extraction model (code needs no model).`,
      )
    )
      return;
    try {
      const r = await this.sourcesApi.rebuildProjectGraph(id);
      this.snack.open(`${r.queued} sources queued for graph extraction`, 'Close', {
        duration: 3000,
      });
    } catch (err) {
      this.snack.open(errorMessage(err), 'Close', { duration: 5000 });
    }
  }

  async retry(sourceId: string): Promise<void> {
    try {
      await this.sourcesApi.reindex(sourceId);
      await this.loadIngestion();
    } catch (err) {
      this.snack.open(errorMessage(err), 'Close', { duration: 5000 });
    }
  }
}
