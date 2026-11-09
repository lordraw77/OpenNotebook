import { DatePipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router } from '@angular/router';

import { TreeNodeDto } from '../../core/api.models';
import { ApiService, errorMessage } from '../../core/api.service';
import { ChatApi, HistoryItem } from '../../core/chat.api';
import { TranslatePipe, i18nKey, t } from '../../core/i18n';
import { breadcrumb } from '../workbench/tree';

const PAGE = 50;
const DAY = 24 * 3600 * 1000;

interface Group {
  label: string;
  items: HistoryItem[];
}

/** Every conversation of the user across scopes: search titles and messages, reopen, export, delete. */
@Component({
  selector: 'app-history',
  imports: [
    TranslatePipe,
    DatePipe,
    FormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressBarModule,
    MatSelectModule,
    MatTooltipModule,
  ],
  template: `
    <div class="history">
      <header class="bar">
        <h2>{{ 'Chat history' | t }}</h2>
        <span class="muted">{{ '{n} conversations' | t: { n: total() } }}</span>
        <span class="spacer"></span>
        <mat-form-field appearance="outline" subscriptSizing="dynamic" class="scope">
          <mat-label>{{ 'Scope' | t }}</mat-label>
          <mat-select [value]="scopeId()" (valueChange)="setScope($event)">
            <mat-option [value]="null">{{ 'Everything' | t }}</mat-option>
            @for (n of nodes(); track n.id) {
              <mat-option [value]="n.id">{{ label(n) }}</mat-option>
            }
          </mat-select>
        </mat-form-field>
        <mat-form-field appearance="outline" subscriptSizing="dynamic" class="search">
          <mat-label>{{ 'Search in conversations' | t }}</mat-label>
          <mat-icon matPrefix>search</mat-icon>
          <input matInput [ngModel]="query()" (ngModelChange)="onQuery($event)" />
        </mat-form-field>
      </header>
      @if (loading()) {
        <mat-progress-bar mode="indeterminate"></mat-progress-bar>
      }
      @if (error()) {
        <p class="error-text">{{ error() }}</p>
      }
      @for (g of groups(); track g.label) {
        <h3 class="group">{{ g.label | t }}</h3>
        @for (c of g.items; track c.id) {
          <article class="row" (click)="open(c)" (keydown.enter)="open(c)" tabindex="0">
            <mat-icon class="kind">{{ c.research ? 'travel_explore' : 'chat' }}</mat-icon>
            <div class="main">
              <div class="title">{{ c.title }}</div>
              <div class="muted small">
                {{ c.scope_name }} ·
                {{
                  c.message_count === 1
                    ? ('1 message' | t)
                    : ('{n} messages' | t: { n: c.message_count })
                }}
                · {{ c.updated_at | date: 'short' }}
              </div>
              @if (c.match) {
                <div class="match">{{ c.match }}</div>
              } @else if (c.first_question && c.first_question !== c.title) {
                <div class="muted small">{{ c.first_question }}</div>
              }
            </div>
            <button
              mat-icon-button
              [matTooltip]="'Download as Markdown' | t"
              [attr.aria-label]="'Download as Markdown' | t"
              (click)="$event.stopPropagation(); download(c)"
            >
              <mat-icon>download</mat-icon>
            </button>
            <button
              mat-icon-button
              [matTooltip]="'Delete' | t"
              [attr.aria-label]="'Delete conversation' | t"
              (click)="$event.stopPropagation(); remove(c)"
            >
              <mat-icon>delete</mat-icon>
            </button>
          </article>
        }
      } @empty {
        @if (!loading()) {
          <p class="muted pad">
            {{
              query()
                ? ('No conversation matches.' | t)
                : ('No conversations yet. Ask a question in the Workbench.' | t)
            }}
          </p>
        }
      }
      @if (items().length < total()) {
        <div class="more">
          <button mat-stroked-button [disabled]="loading()" (click)="more()">
            {{ 'Load more' | t }}
          </button>
        </div>
      }
    </div>
  `,
  styles: `
    .history {
      max-width: 900px;
      margin: 0 auto;
      padding: 16px;
    }
    .bar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 12px;
    }
    .bar h2 {
      margin: 0;
      font: var(--mat-sys-title-large);
    }
    .spacer {
      flex: 1;
    }
    .scope {
      width: 220px;
    }
    .search {
      width: 260px;
    }
    .group {
      margin: 20px 0 6px;
      font: var(--mat-sys-label-large);
      color: var(--mat-sys-on-surface-variant);
    }
    .row {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 10px 12px;
      border: 1px solid var(--mat-sys-outline-variant);
      border-radius: 12px;
      margin-bottom: 8px;
      cursor: pointer;
    }
    .row:hover,
    .row:focus-visible {
      background: var(--mat-sys-surface-container);
      outline: none;
    }
    .kind {
      color: var(--mat-sys-primary);
    }
    .main {
      flex: 1;
      min-width: 0;
    }
    .title {
      font: var(--mat-sys-title-small);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .small {
      font-size: 12px;
    }
    .match {
      font-size: 13px;
      margin-top: 2px;
    }
    .more {
      text-align: center;
      margin: 16px 0;
    }
    .pad {
      padding: 16px;
    }
  `,
})
export class HistoryComponent {
  private readonly api = inject(ApiService);
  private readonly chat = inject(ChatApi);
  private readonly router = inject(Router);

  readonly nodes = signal<TreeNodeDto[]>([]);
  readonly items = signal<HistoryItem[]>([]);
  readonly total = signal(0);
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  readonly query = signal('');
  readonly scopeId = signal<string | null>(null);
  private timer: ReturnType<typeof setTimeout> | null = null;

  /** Today, yesterday, this week and older (by the last message). */
  readonly groups = computed<Group[]>(() => {
    const labels = {
      today: i18nKey('Today'),
      yesterday: i18nKey('Yesterday'),
      week: i18nKey('Last 7 days'),
      older: i18nKey('Older'),
    };
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    const today = start.getTime();
    const buckets = new Map<string, HistoryItem[]>();
    for (const c of this.items()) {
      const at = new Date(c.updated_at).getTime();
      const key =
        at >= today
          ? labels.today
          : at >= today - DAY
            ? labels.yesterday
            : at >= today - 7 * DAY
              ? labels.week
              : labels.older;
      buckets.set(key, [...(buckets.get(key) ?? []), c]);
    }
    return Object.values(labels)
      .filter((l) => buckets.has(l))
      .map((l) => ({ label: l, items: buckets.get(l)! }));
  });

  constructor() {
    void this.api.nodes().then((n) => this.nodes.set(n));
    void this.load(false);
  }

  label(n: TreeNodeDto): string {
    return breadcrumb(this.nodes(), n.id)
      .map((x) => x.name)
      .join(' / ');
  }

  setScope(id: string | null): void {
    this.scopeId.set(id);
    void this.load(false);
  }

  onQuery(text: string): void {
    this.query.set(text);
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.load(false), 300);
  }

  more(): Promise<void> {
    return this.load(true);
  }

  private async load(append: boolean): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const res = await this.chat.history({
        q: this.query(),
        scopeId: this.scopeId(),
        offset: append ? this.items().length : 0,
        limit: PAGE,
      });
      this.items.set(append ? [...this.items(), ...res.items] : res.items);
      this.total.set(res.total);
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.loading.set(false);
    }
  }

  open(c: HistoryItem): void {
    void this.router.navigate(['/workbench'], {
      queryParams: { scope: c.scope_node_id, conversation: c.id },
    });
  }

  download(c: HistoryItem): Promise<void> {
    return this.chat
      .exportMarkdown(c.id, c.title)
      .catch((err) => this.error.set(errorMessage(err)));
  }

  async remove(c: HistoryItem): Promise<void> {
    if (!confirm(t('Delete “{title}”? Its messages are removed too.', { title: c.title }))) return;
    try {
      await this.chat.remove(c.id);
      this.items.update((list) => list.filter((x) => x.id !== c.id));
      this.total.update((n) => Math.max(0, n - 1));
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }
}
