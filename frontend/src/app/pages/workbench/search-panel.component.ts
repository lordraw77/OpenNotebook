import { DecimalPipe } from '@angular/common';
import { Component, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';

import { errorMessage } from '../../core/api.service';
import { SearchHit, SourcesApi } from '../../core/sources.api';
import { TranslatePipe, t } from '../../core/i18n';

/** Hybrid search over the active sources in scope (the same retrieval that feeds the chat). */
@Component({
  selector: 'app-search-panel',
  imports: [
    TranslatePipe,
    FormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    DecimalPipe,
  ],
  template: `
    <div class="results">
      @if (busy()) {
        <mat-progress-bar mode="indeterminate"></mat-progress-bar>
      }
      @if (error()) {
        <p class="error-text">{{ error() }}</p>
      }
      @if (searched() && !busy() && hits().length === 0 && !error()) {
        <p class="muted">{{ 'No passages found in the active sources of this scope.' | t }}</p>
      }
      @if (!searched()) {
        <div class="placeholder">
          <mat-icon>manage_search</mat-icon>
          <p>{{ 'Search the active sources in the selected scope.' | t }}</p>
          <p class="muted">
            {{
              'The same hybrid retrieval feeds the chat: use it to check which passages a question finds.'
                | t
            }}
          </p>
        </div>
      }
      @for (h of hits(); track h.chunk.id; let i = $index) {
        <article class="hit">
          <header>
            <span class="rank">{{ i + 1 }}</span>
            <button type="button" class="title" (click)="openSource.emit(h.source_id)">
              {{ h.source_title }}
            </button>
            <span class="muted">· {{ h.notebook_name }}</span>
            @if (h.chunk.page_start) {
              <span class="cap"
                >p. {{ h.chunk.page_start
                }}{{ h.chunk.page_end !== h.chunk.page_start ? '–' + h.chunk.page_end : '' }}</span
              >
            }
            <span class="spacer"></span>
            <span class="muted score">{{ h.score | number: '1.3-3' }}</span>
          </header>
          @if (h.chunk.heading_path.length) {
            <div class="muted path">{{ h.chunk.heading_path.join(' › ') }}</div>
          }
          <p class="text">{{ h.chunk.text }}</p>
        </article>
      }
      @if (model()) {
        <p class="muted model">{{ 'Embedding model: {model}' | t: { model: model() } }}</p>
      }
    </div>
    <form class="composer" (ngSubmit)="run()">
      <mat-form-field appearance="outline" class="grow" subscriptSizing="dynamic">
        <mat-label>{{
          scopeId() ? ('Search the sources in scope' | t) : ('Select a scope in the tree first' | t)
        }}</mat-label>
        <input matInput name="q" [(ngModel)]="query" [disabled]="!scopeId()" maxlength="2000" />
      </mat-form-field>
      <button mat-flat-button type="submit" [disabled]="!scopeId() || !query.trim() || busy()">
        <mat-icon>search</mat-icon> {{ 'Search' | t }}
      </button>
    </form>
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      flex: 1;
      min-height: 0;
    }
    .results {
      flex: 1;
      overflow: auto;
      padding: 8px 16px;
    }
    .placeholder {
      text-align: center;
      margin: 15vh auto 0;
      max-width: 440px;
    }
    .placeholder mat-icon {
      font-size: 48px;
      width: 48px;
      height: 48px;
      color: var(--mat-sys-primary);
    }
    .hit {
      padding: 12px;
      border: 1px solid var(--mat-sys-outline-variant);
      border-radius: 12px;
      margin-bottom: 10px;
    }
    .hit header {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
    }
    .rank {
      font-weight: 500;
      color: var(--mat-sys-primary);
    }
    .title {
      border: 0;
      background: none;
      color: var(--mat-sys-primary);
      font: inherit;
      font-weight: 500;
      cursor: pointer;
      padding: 0;
    }
    .title:hover {
      text-decoration: underline;
    }
    .spacer {
      flex: 1;
    }
    .path {
      font-size: 12px;
      margin-top: 2px;
    }
    .text {
      white-space: pre-wrap;
      margin: 8px 0 0;
    }
    .score,
    .model {
      font-size: 12px;
    }
    .composer {
      display: flex;
      gap: 8px;
      align-items: center;
      padding: 12px 16px 16px;
    }
    .grow {
      flex: 1;
    }
  `,
})
export class SearchPanelComponent {
  private readonly api = inject(SourcesApi);
  readonly scopeId = input<string | null>(null);
  readonly openSource = output<string>();

  readonly hits = signal<SearchHit[]>([]);
  readonly busy = signal(false);
  readonly searched = signal(false);
  readonly error = signal<string | null>(null);
  readonly model = signal<string | null>(null);
  query = '';

  async run(): Promise<void> {
    const scope = this.scopeId();
    if (!scope || !this.query.trim()) return;
    this.busy.set(true);
    this.error.set(null);
    try {
      const res = await this.api.search(scope, this.query.trim());
      this.hits.set(res.hits);
      this.model.set(res.embedding_model);
    } catch (err) {
      this.hits.set([]);
      this.error.set(errorMessage(err));
    } finally {
      this.busy.set(false);
      this.searched.set(true);
    }
  }
}
