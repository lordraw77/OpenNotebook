import { DatePipe } from '@angular/common';
import { Component, effect, inject, input, output, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';

import { errorMessage } from '../../core/api.service';
import { ChunkDto, SourceDto, SourcesApi, TERMINAL, formatBytes } from '../../core/sources.api';

const PAGE = 50;

@Component({
  selector: 'app-source-detail',
  imports: [DatePipe, MatButtonModule, MatIconModule, MatProgressBarModule, MatTooltipModule],
  template: `
    @if (source(); as s) {
      <div class="detail">
        <header class="head">
          <div>
            <h3>{{ s.title }}</h3>
            <div class="muted">
              {{ s.mime_type }} · {{ size(s.size_bytes) }}
              @if (s.page_count) {
                · {{ s.page_count }} pages
              }
              · {{ s.chunk_count }} {{ s.chunk_count === 1 ? 'chunk' : 'chunks' }}
              @if (s.indexed_at) {
                · indexed {{ s.indexed_at | date: 'short' }}
              }
            </div>
          </div>
          <span class="spacer"></span>
          <span class="status" [class]="s.status">{{ s.status }}</span>
          @if (s.kind !== 'note') {
            <button
              mat-icon-button
              matTooltip="Download original"
              aria-label="Download original"
              (click)="download(s)"
            >
              <mat-icon>download</mat-icon>
            </button>
          }
          @if (canEdit()) {
            <button
              mat-icon-button
              matTooltip="Re-index"
              aria-label="Re-index"
              [disabled]="!terminal(s)"
              (click)="reindex(s)"
            >
              <mat-icon>refresh</mat-icon>
            </button>
            @if (s.kind !== 'note') {
              <button
                mat-icon-button
                matTooltip="Delete"
                aria-label="Delete source"
                (click)="remove(s)"
              >
                <mat-icon>delete</mat-icon>
              </button>
            }
          }
          <button mat-icon-button matTooltip="Close" aria-label="Close" (click)="closed.emit()">
            <mat-icon>close</mat-icon>
          </button>
        </header>
        @if (!terminal(s)) {
          <mat-progress-bar mode="indeterminate"></mat-progress-bar>
        }
        @if (s.error) {
          <p class="error-text">
            <mat-icon inline>error</mat-icon> {{ s.error.message }}
            @if (s.error.code === 'provider_error' && !s.error.final && !terminal(s)) {
              <span class="muted">(retrying automatically)</span>
            }
          </p>
        }
        @for (w of s.warnings; track w) {
          <p class="warn"><mat-icon inline>warning</mat-icon> {{ w }}</p>
        }
        <div class="chunks">
          @for (c of chunks(); track c.id) {
            <article class="chunk">
              <header class="muted">
                #{{ c.ordinal + 1 }}
                @if (c.page_start) {
                  · p. {{ c.page_start }}{{ c.page_end !== c.page_start ? '–' + c.page_end : '' }}
                } @else if (c.line_start) {
                  · lines {{ c.line_start }}–{{ c.line_end }}
                }
                @if (c.heading_path.length) {
                  · {{ c.heading_path.join(' › ') }}
                }
                · {{ c.token_count }} tokens
              </header>
              <p>{{ c.text }}</p>
            </article>
          } @empty {
            @if (terminal(s)) {
              <p class="muted">No chunks.</p>
            }
          }
          @if (more()) {
            <button mat-stroked-button (click)="loadMore(s)">Load more</button>
          }
        </div>
      </div>
    }
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      flex: 1;
      min-height: 0;
    }
    .detail {
      display: flex;
      flex-direction: column;
      min-height: 0;
      flex: 1;
    }
    .head {
      display: flex;
      align-items: center;
      gap: 4px;
      padding: 8px 16px;
    }
    .head h3 {
      font: var(--mat-sys-title-medium);
      margin: 0;
      overflow-wrap: anywhere;
    }
    .spacer {
      flex: 1;
    }
    .status {
      font-size: 12px;
      padding: 2px 10px;
      border-radius: 10px;
      background: var(--mat-sys-secondary-container);
      color: var(--mat-sys-on-secondary-container);
    }
    .status.ready {
      background: var(--mat-sys-primary-container);
      color: var(--mat-sys-on-primary-container);
    }
    .status.failed {
      background: var(--mat-sys-error-container);
      color: var(--mat-sys-on-error-container);
    }
    .error-text,
    .warn {
      padding: 0 16px;
    }
    .warn {
      color: var(--mat-sys-tertiary);
    }
    .chunks {
      overflow: auto;
      padding: 8px 16px 16px;
      flex: 1;
    }
    .chunk {
      border-left: 3px solid var(--mat-sys-outline-variant);
      padding: 4px 12px;
      margin-bottom: 12px;
    }
    .chunk header {
      font-size: 12px;
    }
    .chunk p {
      white-space: pre-wrap;
      margin: 4px 0 0;
    }
  `,
})
export class SourceDetailComponent {
  private readonly api = inject(SourcesApi);
  private readonly snack = inject(MatSnackBar);

  readonly source = input<SourceDto | null>(null);
  readonly canEdit = input(false);
  readonly closed = output<void>();
  readonly changed = output<void>();

  readonly chunks = signal<ChunkDto[]>([]);
  readonly more = signal(false);
  private loadedFor: string | null = null;

  protected readonly size = formatBytes;
  protected terminal = (s: SourceDto) => TERMINAL.includes(s.status);

  constructor() {
    // Reload chunks when another source is shown, or when the shown source becomes ready.
    effect(() => {
      const s = this.source();
      const key = s ? `${s.id}:${s.status}:${s.chunk_count}` : null;
      if (key !== this.loadedFor) {
        this.loadedFor = key;
        this.chunks.set([]);
        if (s && s.status === 'ready') void this.loadMore(s);
      }
    });
  }

  async loadMore(s: SourceDto): Promise<void> {
    const page = await this.api.chunks(s.id, this.chunks().length, PAGE);
    this.chunks.update((c) => [...c, ...page]);
    this.more.set(page.length === PAGE);
  }

  async download(s: SourceDto): Promise<void> {
    await this.act(() => this.api.download(s));
  }

  async reindex(s: SourceDto): Promise<void> {
    await this.act(() => this.api.reindex(s.id), 'Re-indexing queued');
  }

  async remove(s: SourceDto): Promise<void> {
    if (!confirm(`Delete “${s.title}”? Its chunks and vectors are removed too.`)) return;
    await this.act(() => this.api.remove(s.id), 'Source deleted');
    this.closed.emit();
  }

  private async act(fn: () => Promise<unknown>, ok?: string): Promise<void> {
    try {
      await fn();
      if (ok) this.snack.open(ok, 'Close', { duration: 3000 });
      this.changed.emit();
    } catch (err) {
      this.snack.open(errorMessage(err), 'Close', { duration: 5000 });
    }
  }
}
