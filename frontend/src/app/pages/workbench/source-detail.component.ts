import { DatePipe } from '@angular/common';
import { Component, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';

import { errorMessage } from '../../core/api.service';
import {
  ChunkDto,
  GIT_INTERVALS,
  GitSettings,
  SourceDto,
  SourcesApi,
  TERMINAL,
  formatBytes,
  statusLabel,
} from '../../core/sources.api';
import { TranslatePipe, t } from '../../core/i18n';

const PAGE = 50;

@Component({
  selector: 'app-source-detail',
  imports: [
    TranslatePipe,
    DatePipe,
    FormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatIconModule,
    MatProgressBarModule,
    MatTooltipModule,
  ],
  template: `
    @if (source(); as s) {
      <div class="detail">
        <header class="head">
          <div>
            <h3>{{ s.title }}</h3>
            <div class="muted">
              {{ s.mime_type
              }}{{ s.details.rendition === 'pdf' ? ' ' + ('(shown as PDF)' | t) : '' }} ·
              {{ size(s.size_bytes) }}
              @if (s.page_count) {
                · {{ '{n} pages' | t: { n: s.page_count } }}
              }
              ·
              {{
                s.chunk_count === 1
                  ? ('{n} chunk' | t: { n: 1 })
                  : ('{n} chunks' | t: { n: s.chunk_count })
              }}
              @if (s.indexed_at) {
                · {{ 'indexed {date}' | t: { date: s.indexed_at | date: 'short' } }}
              }
            </div>
          </div>
          <span class="spacer"></span>
          <span class="status" [class]="s.status">{{ statusLabel(s.status) }}</span>
          @if (s.kind !== 'note') {
            <button
              mat-icon-button
              [matTooltip]="'Download original' | t"
              [attr.aria-label]="'Download original' | t"
              (click)="download(s)"
            >
              <mat-icon>download</mat-icon>
            </button>
          }
          @if (canEdit()) {
            <button
              mat-icon-button
              [matTooltip]="'Re-index' | t"
              [attr.aria-label]="'Re-index' | t"
              [disabled]="!terminal(s)"
              (click)="reindex(s)"
            >
              <mat-icon>refresh</mat-icon>
            </button>
            @if (s.kind !== 'note') {
              <button
                mat-icon-button
                [matTooltip]="'Delete' | t"
                [attr.aria-label]="'Delete source' | t"
                (click)="remove(s)"
              >
                <mat-icon>delete</mat-icon>
              </button>
            }
          }
          <button
            mat-icon-button
            [matTooltip]="'Close' | t"
            [attr.aria-label]="'Close' | t"
            (click)="closed.emit()"
          >
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
              <span class="muted">{{ '(retrying automatically)' | t }}</span>
            }
          </p>
        }
        @for (w of s.warnings; track w) {
          <p class="warn"><mat-icon inline>warning</mat-icon> {{ w }}</p>
        }
        <div class="chunks">
          @if (s.uri) {
            <p class="meta-line">
              <mat-icon inline>link</mat-icon>
              <a [href]="s.details.final_url ?? s.uri" target="_blank" rel="noopener noreferrer">{{
                s.details.final_url ?? s.uri
              }}</a>
              @if (s.details.fetched_at) {
                <span class="muted"
                  >·
                  {{ 'fetched {date}' | t: { date: s.details.fetched_at | date: 'short' } }}</span
                >
              }
              @if (s.details.crawl?.links_followed) {
                <span class="muted"
                  >·
                  {{ '{n} linked pages added' | t: { n: s.details.crawl?.links_followed } }}</span
                >
              }
            </p>
          }
          @if (s.language) {
            <p class="meta-line muted"><mat-icon inline>code</mat-icon> {{ s.language }}</p>
          }
          @switch (s.summary_status) {
            @case ('done') {
              <section class="summary">
                <h4><mat-icon inline>auto_awesome</mat-icon> {{ 'Summary' | t }}</h4>
                <p>{{ s.summary }}</p>
                @if (s.suggested_questions.length) {
                  <div class="questions">
                    @for (q of s.suggested_questions; track q) {
                      <button
                        type="button"
                        class="question"
                        [matTooltip]="'Ask in the chat' | t"
                        (click)="ask.emit(q)"
                      >
                        <mat-icon inline>chat_bubble</mat-icon> {{ q }}
                      </button>
                    }
                  </div>
                }
              </section>
            }
            @case ('pending') {
              <p class="muted meta-line">
                <mat-icon inline>hourglass_top</mat-icon> {{ 'Summary being generated…' | t }}
              </p>
            }
            @case ('failed') {
              <p class="muted meta-line">
                <mat-icon inline>info</mat-icon>
                {{ 'No summary: {error}' | t: { error: s.summary_error } }}
              </p>
            }
          }
          @if (s.details.git; as g) {
            <section class="summary">
              <h4><mat-icon inline>source</mat-icon> {{ 'Git repository' | t }}</h4>
              <p>
                <code>{{ g.url }}</code> · {{ g.branch ?? ('default branch' | t) }}
                @if (g.commit) {
                  · <code>{{ g.commit.slice(0, 10) }}</code>
                }
              </p>
              @if (g.synced_at) {
                <p class="muted">
                  {{ 'synchronised {date}' | t: { date: g.synced_at | date: 'short' } }} ·
                  {{
                    '{added} added, {changed} changed, {removed} removed, {files} files'
                      | t
                        : {
                            added: g.added ?? 0,
                            changed: g.changed ?? 0,
                            removed: g.removed ?? 0,
                            files: g.files ?? 0,
                          }
                  }}
                </p>
              }
              @if (canEdit()) {
                <div class="git-row">
                  <button mat-flat-button [disabled]="!terminal(s)" (click)="sync(s)">
                    <mat-icon>sync</mat-icon> {{ 'Sync now' | t }}
                  </button>
                  <mat-form-field appearance="outline" subscriptSizing="dynamic">
                    <mat-label>{{ 'Synchronise' | t }}</mat-label>
                    <mat-select
                      [ngModel]="g.sync_interval_minutes"
                      (ngModelChange)="saveGit(s, { sync_interval_minutes: $event })"
                    >
                      @for (o of intervals; track o.minutes) {
                        <mat-option [value]="o.minutes">{{ o.label | t }}</mat-option>
                      }
                    </mat-select>
                  </mat-form-field>
                  <mat-form-field appearance="outline" subscriptSizing="dynamic">
                    <mat-label>{{ 'Branch' | t }}</mat-label>
                    <input
                      matInput
                      [ngModel]="g.branch ?? ''"
                      (change)="saveGit(s, { branch: $any($event.target).value.trim() || null })"
                    />
                  </mat-form-field>
                  <mat-form-field appearance="outline" subscriptSizing="dynamic">
                    <mat-label>{{
                      g.token_set ? ('Replace token' | t) : ('Access token' | t)
                    }}</mat-label>
                    <input
                      matInput
                      type="password"
                      autocomplete="off"
                      (change)="saveGit(s, { token: $any($event.target).value })"
                    />
                  </mat-form-field>
                </div>
                <mat-form-field appearance="outline" subscriptSizing="dynamic" class="wide">
                  <mat-label>{{ 'Exclude (patterns, one per line)' | t }}</mat-label>
                  <textarea
                    matInput
                    rows="2"
                    [ngModel]="
                      g.exclude.join(
                        '
'
                      )
                    "
                    (change)="saveGit(s, { exclude: lines($any($event.target).value) })"
                    placeholder="docs/generated/*&#10;*.csv"
                  ></textarea>
                </mat-form-field>
              }
            </section>
          }
          @if (s.details.archive; as a) {
            <section class="summary">
              <h4><mat-icon inline>folder_zip</mat-icon> {{ 'Archive' | t }}</h4>
              <p>
                {{
                  a.files === 1
                    ? ('1 file indexed as a source' | t)
                    : ('{n} files indexed as sources' | t: { n: a.files })
                }}
                · {{ '{n} skipped' | t: { n: a.skipped_count } }} ·
                {{ '{size} uncompressed' | t: { size: size(a.uncompressed_bytes) } }} ·
                {{ a.format.toUpperCase() }}
              </p>
              @if (a.skipped.length) {
                <details>
                  <summary>{{ 'Skipped files' | t }}</summary>
                  <ul class="skipped">
                    @for (k of a.skipped; track k.path + $index) {
                      <li>
                        <code>{{ k.path }}</code> <span class="muted">{{ k.reason }}</span>
                      </li>
                    }
                  </ul>
                </details>
              }
            </section>
          }
          @for (c of chunks(); track c.id) {
            <article class="chunk">
              <header class="muted">
                #{{ c.ordinal + 1 }}
                @if (c.page_start) {
                  · p. {{ c.page_start }}{{ c.page_end !== c.page_start ? '–' + c.page_end : '' }}
                } @else if (c.line_start) {
                  · {{ 'lines {start}–{end}' | t: { start: c.line_start, end: c.line_end } }}
                }
                @if (c.heading_path.length) {
                  · {{ c.heading_path.join(' › ') }}
                }
                · {{ '{n} tokens' | t: { n: c.token_count } }}
              </header>
              <p>{{ c.text }}</p>
            </article>
          } @empty {
            @if (terminal(s)) {
              <p class="muted">{{ 'No chunks.' | t }}</p>
            }
          }
          @if (more()) {
            <button mat-stroked-button (click)="loadMore(s)">{{ 'Load more' | t }}</button>
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
    .meta-line {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
      margin: 0 0 8px;
      overflow-wrap: anywhere;
    }
    .summary {
      padding: 12px 14px;
      margin-bottom: 12px;
      border-radius: 12px;
      background: var(--mat-sys-surface-container);
      border: 1px solid var(--mat-sys-outline-variant);
    }
    .git-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin: 8px 0;
    }
    .wide {
      width: 100%;
    }
    .summary h4 {
      margin: 0 0 6px;
      font: var(--mat-sys-title-small);
      color: var(--mat-sys-primary);
    }
    .summary p {
      margin: 0;
      line-height: 1.55;
    }
    .questions {
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-top: 10px;
    }
    .question {
      text-align: left;
      padding: 6px 12px;
      border-radius: 14px;
      border: 1px solid var(--mat-sys-outline-variant);
      background: var(--mat-sys-surface-container-low);
      color: var(--mat-sys-on-surface);
      font: var(--mat-sys-body-medium);
      cursor: pointer;
    }
    .question:hover {
      border-color: var(--mat-sys-primary);
      color: var(--mat-sys-primary);
    }
    .skipped {
      max-height: 200px;
      overflow: auto;
      font-size: 13px;
      padding-left: 18px;
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
  protected readonly statusLabel = statusLabel;
  private readonly api = inject(SourcesApi);
  private readonly snack = inject(MatSnackBar);

  readonly source = input<SourceDto | null>(null);
  readonly canEdit = input(false);
  readonly closed = output<void>();
  readonly changed = output<void>();
  /** A suggested question was clicked: ask it in the chat. */
  readonly ask = output<string>();

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

  protected readonly intervals = GIT_INTERVALS;

  lines(text: string): string[] {
    return text
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l);
  }

  async sync(s: SourceDto): Promise<void> {
    await this.act(() => this.api.sync(s.id), t('Sync queued'));
  }

  async saveGit(s: SourceDto, settings: GitSettings): Promise<void> {
    await this.act(() => this.api.updateGit(s.id, settings), t('Repository settings saved'));
  }

  async reindex(s: SourceDto): Promise<void> {
    await this.act(() => this.api.reindex(s.id), 'Re-indexing queued');
  }

  async remove(s: SourceDto): Promise<void> {
    if (
      !confirm(t('Delete “{title}”? Its chunks and vectors are removed too.', { title: s.title }))
    )
      return;
    await this.act(() => this.api.remove(s.id), t('Source deleted'));
    this.closed.emit();
  }

  private async act(fn: () => Promise<unknown>, ok?: string): Promise<void> {
    try {
      await fn();
      if (ok) this.snack.open(ok, t('Close'), { duration: 3000 });
      this.changed.emit();
    } catch (err) {
      this.snack.open(errorMessage(err), t('Close'), { duration: 5000 });
    }
  }
}
