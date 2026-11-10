import { DatePipe } from '@angular/common';
import { Component, DestroyRef, computed, effect, inject, input, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';

import { TreeNodeDto } from '../../core/api.models';
import { ApiService, errorMessage } from '../../core/api.service';
import {
  SourceDto,
  SourcesApi,
  TERMINAL,
  UploadResult,
  formatBytes,
  statusLabel,
  GIT_INTERVALS,
} from '../../core/sources.api';
import { KIND_ICONS, breadcrumb, hasRole, sourceIcon } from '../workbench/tree';
import { TranslatePipe, t } from '../../core/i18n';

// Any file can be dropped: the type is detected from the content on the server.
const ACCEPT = '';

@Component({
  selector: 'app-upload',
  imports: [
    TranslatePipe,
    DatePipe,
    MatCardModule,
    MatFormFieldModule,
    MatSelectModule,
    MatInputModule,
    MatIconModule,
    MatButtonModule,
    MatProgressBarModule,
    MatTableModule,
    MatTooltipModule,
  ],
  template: `
    <div class="page">
      <h1>{{ 'Upload sources' | t }}</h1>
      <mat-form-field appearance="outline" class="target">
        <mat-label>{{ 'Upload to (project, workspace or notebook)' | t }}</mat-label>
        <mat-select [value]="target()" (valueChange)="target.set($event)">
          @for (n of notebooks(); track n.id) {
            <mat-option [value]="n.id"
              ><mat-icon>{{ kindIcons[n.kind] }}</mat-icon> {{ label(n) }}</mat-option
            >
          } @empty {
            <mat-option disabled>{{
              'Nothing you can upload to: ask for editor access' | t
            }}</mat-option>
          }
        </mat-select>
      </mat-form-field>

      <mat-card
        appearance="outlined"
        class="drop"
        [class.over]="dragOver()"
        [class.disabled]="!target()"
        (dragover)="$event.preventDefault(); dragOver.set(!!target())"
        (dragleave)="dragOver.set(false)"
        (drop)="onDrop($event)"
      >
        <mat-icon>cloud_upload</mat-icon>
        <p>{{ 'Drop documents, source code, images or archives here' | t }}</p>
        <button mat-flat-button [disabled]="!target() || uploading()" (click)="picker.click()">
          {{ 'Choose files' | t }}
        </button>
        <input #picker type="file" multiple hidden [accept]="accept" (change)="onPick(picker)" />
        <p class="muted small">
          {{
            'PDF (scanned pages via OCR), DOCX, Markdown, text, HTML · code (C, C++, Python, JS/TS, Java, Go, Rust, C#, PHP, Ruby, shell and more) · PNG, JPEG, WebP, TIFF, GIF (OCR + description) · ZIP, TAR, 7z and RAR archives (each file becomes a source)'
              | t
          }}
        </p>
      </mat-card>

      <mat-card appearance="outlined" class="web" [class.disabled]="!target()">
        <h2 class="section-inline"><mat-icon>language</mat-icon> {{ 'Add web pages' | t }}</h2>
        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>{{ 'URLs (one per line)' | t }}</mat-label>
          <textarea
            matInput
            rows="3"
            [value]="urls()"
            (input)="urls.set($any($event.target).value)"
            [disabled]="!target()"
            placeholder="https://example.com/docs/"
          ></textarea>
        </mat-form-field>
        <div class="web-row">
          <mat-form-field appearance="outline" subscriptSizing="dynamic" class="narrow">
            <mat-label>{{ 'Follow links' | t }}</mat-label>
            <mat-select [value]="crawlDepth()" (valueChange)="crawlDepth.set($event)">
              <mat-option [value]="0">{{ 'No, only these pages' | t }}</mat-option>
              <mat-option [value]="1">{{ '1 level, same site' | t }}</mat-option>
              <mat-option [value]="2">{{ '2 levels, same site' | t }}</mat-option>
            </mat-select>
          </mat-form-field>
          @if (crawlDepth() > 0) {
            <mat-form-field appearance="outline" subscriptSizing="dynamic" class="narrow">
              <mat-label>{{ 'Max pages' | t }}</mat-label>
              <input
                matInput
                type="number"
                min="1"
                max="50"
                [value]="maxPages()"
                (input)="maxPages.set(+$any($event.target).value || 20)"
              />
            </mat-form-field>
          }
          <span class="spacer"></span>
          <button
            mat-flat-button
            [disabled]="!target() || !urlList().length || adding()"
            (click)="addWeb()"
          >
            <mat-icon>add_link</mat-icon>
            {{
              urlList().length === 1
                ? ('Add 1 page' | t)
                : urlList().length
                  ? ('Add {n} pages' | t: { n: urlList().length })
                  : ('Add pages' | t)
            }}
          </button>
        </div>
        <p class="muted small">
          {{
            'Pages are fetched by the server: main text only (menus and footers removed), robots.txt is respected when following links, and private network addresses are refused.'
              | t
          }}
        </p>
      </mat-card>

      <mat-card appearance="outlined" class="web" [class.disabled]="!target()">
        <h2 class="section-inline"><mat-icon>source</mat-icon> {{ 'Add a git repository' | t }}</h2>
        <div class="web-row">
          <mat-form-field appearance="outline" subscriptSizing="dynamic" class="grow">
            <mat-label>{{ 'Repository URL' | t }}</mat-label>
            <input
              matInput
              [value]="gitUrl()"
              (input)="gitUrl.set($any($event.target).value)"
              [disabled]="!target()"
              placeholder="http://gitlab.lan/team/project.git"
            />
          </mat-form-field>
          <mat-form-field appearance="outline" subscriptSizing="dynamic" class="narrow">
            <mat-label>{{ 'Branch' | t }}</mat-label>
            <input
              matInput
              [value]="gitBranch()"
              (input)="gitBranch.set($any($event.target).value)"
              [disabled]="!target()"
              placeholder="main"
            />
          </mat-form-field>
        </div>
        <div class="web-row">
          <mat-form-field appearance="outline" subscriptSizing="dynamic" class="grow">
            <mat-label>{{ 'Access token (private repositories)' | t }}</mat-label>
            <input
              matInput
              type="password"
              autocomplete="off"
              [value]="gitToken()"
              (input)="gitToken.set($any($event.target).value)"
              [disabled]="!target()"
            />
          </mat-form-field>
          <mat-form-field appearance="outline" subscriptSizing="dynamic" class="narrow">
            <mat-label>{{ 'Synchronise' | t }}</mat-label>
            <mat-select [value]="gitInterval()" (valueChange)="gitInterval.set($event)">
              @for (o of gitIntervals; track o.minutes) {
                <mat-option [value]="o.minutes">{{ o.label | t }}</mat-option>
              }
            </mat-select>
          </mat-form-field>
          <button
            mat-flat-button
            [disabled]="!target() || !gitUrl().trim() || adding()"
            (click)="addGit()"
          >
            <mat-icon>add</mat-icon> {{ 'Add repository' | t }}
          </button>
        </div>
        <p class="muted small">
          {{
            'The server clones the branch and indexes each file; later syncs only process what changed. Only hosts allowed by the administrator (GIT_ALLOWED_HOSTS) can be used. The token is stored encrypted and never shown again.'
              | t
          }}
        </p>
      </mat-card>

      @if (uploading()) {
        <mat-progress-bar mode="determinate" [value]="progress() * 100"></mat-progress-bar>
      }
      @if (error()) {
        <p class="error-text">{{ error() }}</p>
      }
      @if (results().length) {
        <ul class="results">
          @for (r of results(); track r.filename + $index) {
            <li>
              @if (r.error) {
                <mat-icon class="bad">block</mat-icon> {{ r.filename }}:
                <span class="error-text">{{ r.error }}</span>
              } @else if (r.duplicate) {
                <mat-icon class="muted">content_copy</mat-icon>
                {{ '{name}: already in this notebook' | t: { name: r.filename } }}
              } @else {
                <mat-icon class="ok">check_circle</mat-icon>
                {{ '{name}: queued for indexing' | t: { name: r.filename } }}
              }
            </li>
          }
        </ul>
      }

      @if (target()) {
        <h2 class="section">{{ 'Sources here and inside' | t }}</h2>
        <div class="table-wrap">
          <table mat-table [dataSource]="sources()">
            <ng-container matColumnDef="title">
              <th mat-header-cell *matHeaderCellDef>{{ 'Source' | t }}</th>
              <td mat-cell *matCellDef="let s">
                <span class="kind"
                  ><mat-icon>{{ sourceIcon(s) }}</mat-icon> {{ s.parent_source_id ? '↳ ' : ''
                  }}{{ s.title }}</span
                >
              </td>
            </ng-container>
            <ng-container matColumnDef="size">
              <th mat-header-cell *matHeaderCellDef>{{ 'Size' | t }}</th>
              <td mat-cell *matCellDef="let s">{{ size(s.size_bytes) }}</td>
            </ng-container>
            <ng-container matColumnDef="status">
              <th mat-header-cell *matHeaderCellDef>{{ 'Status' | t }}</th>
              <td mat-cell *matCellDef="let s">
                <span class="status" [class]="s.status" [matTooltip]="s.error?.message ?? ''">{{
                  statusLabel(s.status)
                }}</span>
                @if (s.warnings.length) {
                  <mat-icon class="warn" [matTooltip]="s.warnings.join(' ')">warning</mat-icon>
                }
              </td>
            </ng-container>
            <ng-container matColumnDef="chunks">
              <th mat-header-cell *matHeaderCellDef>{{ 'Chunks' | t }}</th>
              <td mat-cell *matCellDef="let s">{{ s.chunk_count }}</td>
            </ng-container>
            <ng-container matColumnDef="added">
              <th mat-header-cell *matHeaderCellDef>{{ 'Added' | t }}</th>
              <td mat-cell *matCellDef="let s">{{ s.created_at | date: 'short' }}</td>
            </ng-container>
            <tr mat-header-row *matHeaderRowDef="columns"></tr>
            <tr mat-row *matRowDef="let s; columns: columns"></tr>
            <tr class="mat-row" *matNoDataRow>
              <td class="mat-cell muted" [attr.colspan]="columns.length">
                {{ 'No sources yet.' | t }}
              </td>
            </tr>
          </table>
        </div>
      }
    </div>
  `,
  styles: `
    .target {
      width: min(560px, 100%);
    }
    .drop {
      display: grid;
      place-items: center;
      gap: 8px;
      text-align: center;
      padding: 32px 16px;
      border-style: dashed;
    }
    .drop.over {
      background: var(--mat-sys-secondary-container);
    }
    .drop.disabled {
      opacity: 0.6;
    }
    .drop mat-icon {
      font-size: 48px;
      width: 48px;
      height: 48px;
      color: var(--mat-sys-primary);
    }
    .small {
      font-size: 12px;
      margin: 0;
    }
    .web {
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding: 16px;
      margin-top: 16px;
    }
    .web.disabled {
      opacity: 0.6;
    }
    .section-inline {
      display: flex;
      align-items: center;
      gap: 8px;
      font: var(--mat-sys-title-medium);
      margin: 0;
    }
    .web-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }
    .narrow {
      width: 200px;
    }
    .spacer {
      flex: 1;
    }
    .kind {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      overflow-wrap: anywhere;
    }
    .kind mat-icon {
      font-size: 18px;
      width: 18px;
      height: 18px;
      color: var(--mat-sys-primary);
      flex: none;
    }
    .results {
      list-style: none;
      padding: 0;
    }
    .results li {
      display: flex;
      align-items: center;
      gap: 6px;
      margin: 4px 0;
    }
    .ok {
      color: var(--mat-sys-primary);
    }
    .bad {
      color: var(--mat-sys-error);
    }
    .section {
      font: var(--mat-sys-title-medium);
      margin: 24px 0 8px;
    }
    .table-wrap {
      overflow-x: auto;
    }
    table {
      width: 100%;
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
    .warn {
      font-size: 18px;
      width: 18px;
      height: 18px;
      vertical-align: middle;
      color: var(--mat-sys-tertiary);
    }
  `,
})
export class UploadComponent {
  protected readonly statusLabel = statusLabel;
  private readonly api = inject(ApiService);
  private readonly sourcesApi = inject(SourcesApi);

  /** Optional ?notebook=<id> preselection (router input binding). */
  readonly notebook = input<string | undefined>();

  private readonly all = signal<TreeNodeDto[]>([]);
  /** Any node the user can edit: sources may be attached to projects, workspaces and notebooks. */
  readonly notebooks = computed(() => this.all().filter((n) => hasRole(n, 'editor')));
  protected readonly kindIcons = KIND_ICONS;
  readonly target = signal<string | null>(null);
  readonly sources = signal<SourceDto[]>([]);
  readonly results = signal<UploadResult[]>([]);
  readonly uploading = signal(false);
  readonly progress = signal(0);
  readonly error = signal<string | null>(null);
  readonly dragOver = signal(false);
  readonly columns = ['title', 'size', 'status', 'chunks', 'added'];
  protected readonly accept = ACCEPT;
  protected readonly sourceIcon = sourceIcon;
  readonly urls = signal('');
  readonly urlList = computed(() =>
    this.urls()
      .split(/\s+/)
      .map((u) => u.trim())
      .filter((u) => u.length > 0),
  );
  readonly crawlDepth = signal(0);
  readonly maxPages = signal(20);
  readonly adding = signal(false);
  readonly gitUrl = signal('');
  readonly gitBranch = signal('');
  readonly gitToken = signal('');
  readonly gitInterval = signal(0);
  protected readonly gitIntervals = GIT_INTERVALS;
  protected readonly size = formatBytes;

  constructor() {
    void this.api.nodes().then((n) => {
      this.all.set(n);
      const wanted = this.notebook();
      if (wanted && this.notebooks().some((x) => x.id === wanted)) this.target.set(wanted);
    });
    effect(() => {
      const t = this.target();
      this.results.set([]);
      void this.loadSources(t);
    });
    const timer = setInterval(() => {
      if (this.sources().some((s) => !TERMINAL.includes(s.status)))
        void this.loadSources(this.target());
    }, 3000);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  label(n: TreeNodeDto): string {
    return breadcrumb(this.all(), n.id)
      .map((x) => x.name)
      .join(' / ');
  }

  async addWeb(): Promise<void> {
    const target = this.target();
    if (!target) return;
    this.adding.set(true);
    this.error.set(null);
    try {
      const res = await this.sourcesApi.addWeb(
        target,
        this.urlList().slice(0, 20),
        this.crawlDepth(),
        this.crawlDepth() ? this.maxPages() : null,
      );
      this.results.set(res);
      if (res.every((r) => !r.error)) this.urls.set('');
      await this.loadSources(target);
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.adding.set(false);
    }
  }

  async addGit(): Promise<void> {
    const target = this.target();
    if (!target) return;
    this.adding.set(true);
    this.error.set(null);
    try {
      await this.sourcesApi.addGit(target, this.gitUrl().trim(), {
        branch: this.gitBranch().trim() || null,
        token: this.gitToken() || null,
        sync_interval_minutes: this.gitInterval(),
      });
      this.gitUrl.set('');
      this.gitToken.set('');
      await this.loadSources(target);
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.adding.set(false);
    }
  }

  private async loadSources(notebookId: string | null): Promise<void> {
    // sources directly in the target node (capped: the tree pages through very large nodes)
    this.sources.set(
      notebookId
        ? (await this.sourcesApi.page({ nodeId: notebookId, limit: 200 })).items.filter(
            (s) => s.kind !== 'note',
          )
        : [],
    );
  }

  onPick(input: HTMLInputElement): void {
    const files = Array.from(input.files ?? []);
    input.value = '';
    this.send(files);
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragOver.set(false);
    this.send(Array.from(event.dataTransfer?.files ?? []));
  }

  private send(files: File[]): void {
    const target = this.target();
    if (!target || files.length === 0) return;
    this.uploading.set(true);
    this.progress.set(0);
    this.error.set(null);
    this.sourcesApi.upload(target, files).subscribe({
      next: (e) => {
        if ('progress' in e) this.progress.set(e.progress);
        else this.results.set(e.done);
      },
      error: (err) => {
        this.error.set(errorMessage(err));
        this.uploading.set(false);
      },
      complete: () => {
        this.uploading.set(false);
        void this.loadSources(target);
      },
    });
  }
}
