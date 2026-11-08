import {
  Component,
  DestroyRef,
  ElementRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist';

import { errorMessage } from '../../core/api.service';
import { Citation, SourcesApi, citationLocation } from '../../core/sources.api';

interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** pdf.js is loaded on first use only (it is large); the worker is served from /pdfjs. */
async function loadPdfJs() {
  const pdfjs = await import('pdfjs-dist');
  pdfjs.GlobalWorkerOptions.workerSrc = '/pdfjs/pdf.worker.min.mjs';
  return pdfjs;
}

/**
 * Opens a cited passage in its source: PDFs at the cited page with the passage boxes highlighted,
 * other sources as extracted text with the passage marked (chunk character offsets).
 */
@Component({
  selector: 'app-source-viewer',
  imports: [MatButtonModule, MatIconModule, MatProgressBarModule, MatTooltipModule],
  template: `
    @let c = citation();
    <header class="head">
      <button
        mat-icon-button
        aria-label="Back to the chat"
        matTooltip="Back"
        (click)="closed.emit()"
      >
        <mat-icon>arrow_back</mat-icon>
      </button>
      <div class="titles">
        <h3 [title]="c.source_title">{{ c.source_title }}</h3>
        <div class="muted">
          {{ c.notebook_name }}
          @if (location()) {
            · {{ location() }}
          }
          @if (c.heading_path.length) {
            · {{ c.heading_path.join(' › ') }}
          }
        </div>
      </div>
      <span class="spacer"></span>
      @if (isPdf() && pageCount()) {
        <button
          mat-icon-button
          aria-label="Previous page"
          [disabled]="page() <= 1"
          (click)="page.set(page() - 1)"
        >
          <mat-icon>chevron_left</mat-icon>
        </button>
        <span class="pager">{{ page() }} / {{ pageCount() }}</span>
        <button
          mat-icon-button
          aria-label="Next page"
          [disabled]="page() >= pageCount()"
          (click)="page.set(page() + 1)"
        >
          <mat-icon>chevron_right</mat-icon>
        </button>
      }
      <button
        mat-icon-button
        matTooltip="Source details"
        aria-label="Source details"
        (click)="details.emit(c.source_id)"
      >
        <mat-icon>info</mat-icon>
      </button>
    </header>
    @if (loading()) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    }
    @if (error()) {
      <p class="error-text pad">{{ error() }}</p>
      @if (c.text || c.excerpt) {
        <blockquote class="pad">{{ c.text || c.excerpt }}</blockquote>
      }
    }
    <div class="body" #body>
      @if (isPdf()) {
        <div
          class="pdf-page"
          [style.width.px]="pageSize().width"
          [style.height.px]="pageSize().height"
        >
          <canvas #canvas></canvas>
          @for (b of boxes(); track $index) {
            <div
              class="hl"
              [style.left.px]="b.left"
              [style.top.px]="b.top"
              [style.width.px]="b.width"
              [style.height.px]="b.height"
            ></div>
          }
        </div>
      } @else if (text() !== null) {
        @if (imageUrl()) {
          <img class="image" [src]="imageUrl()" [alt]="c.source_title" />
        }
        <pre
          class="text"
          [class.code]="
            c.source_kind === 'code'
          ">{{ before() }}<mark #mark>{{ marked() }}</mark>{{ after() }}</pre>
      }
    </div>
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      flex: 1;
      min-height: 0;
    }
    .head {
      display: flex;
      align-items: center;
      gap: 4px;
      padding: 4px 8px;
      border-bottom: 1px solid var(--mat-sys-outline-variant);
    }
    .titles {
      min-width: 0;
    }
    h3 {
      margin: 0;
      font: var(--mat-sys-title-medium);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .titles .muted {
      font-size: 12px;
    }
    .spacer {
      flex: 1;
    }
    .pager {
      font: var(--mat-sys-label-large);
      white-space: nowrap;
    }
    .body {
      flex: 1;
      overflow: auto;
      padding: 16px;
      background: var(--mat-sys-surface-container-low);
    }
    .pdf-page {
      position: relative;
      margin: 0 auto;
      box-shadow: 0 2px 12px rgb(0 0 0 / 25%);
      background: #fff;
    }
    canvas {
      display: block;
    }
    .hl {
      position: absolute;
      background: color-mix(in srgb, var(--mat-sys-tertiary) 28%, transparent);
      outline: 2px solid var(--mat-sys-tertiary);
      border-radius: 2px;
      pointer-events: none;
    }
    .text {
      white-space: pre-wrap;
      word-break: break-word;
      font: var(--mat-sys-body-medium);
      line-height: 1.6;
      margin: 0 auto;
      max-width: 860px;
    }
    .text.code {
      font-family: ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace;
      font-size: 13px;
      line-height: 1.5;
      white-space: pre;
      overflow-x: auto;
      max-width: none;
    }
    .image {
      display: block;
      max-width: 100%;
      max-height: 50vh;
      margin: 0 auto 16px;
      border-radius: 8px;
      box-shadow: 0 2px 12px rgb(0 0 0 / 25%);
    }
    mark {
      background: color-mix(in srgb, var(--mat-sys-tertiary) 26%, transparent);
      color: inherit;
      border-radius: 2px;
      box-shadow: -3px 0 0 var(--mat-sys-tertiary);
      box-decoration-break: clone;
      -webkit-box-decoration-break: clone;
    }
    .pad {
      padding: 0 16px;
    }
    blockquote {
      border-left: 3px solid var(--mat-sys-outline);
      margin: 8px 16px;
      white-space: pre-wrap;
    }
  `,
})
export class SourceViewerComponent {
  private readonly api = inject(SourcesApi);
  readonly citation = input.required<Citation>();
  readonly closed = output<void>();
  readonly details = output<string>();

  private readonly bodyEl = viewChild<ElementRef<HTMLElement>>('body');
  private readonly canvasEl = viewChild<ElementRef<HTMLCanvasElement>>('canvas');
  private readonly markEl = viewChild<ElementRef<HTMLElement>>('mark');

  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  readonly location = computed(() => citationLocation(this.citation()));
  readonly isPdf = computed(() => this.citation().mime_type === 'application/pdf');

  // PDF state
  private pdf: { sourceId: string; doc: PDFDocumentProxy } | null = null;
  private renderTask: RenderTask | null = null;
  readonly page = signal(1);
  readonly pageCount = signal(0);
  readonly pageSize = signal({ width: 0, height: 0 });
  readonly boxes = signal<Box[]>([]);

  // text state (images: the picture is shown above its OCR text and description)
  readonly text = signal<string | null>(null);
  readonly imageUrl = signal<string | null>(null);
  readonly before = computed(() => (this.text() ?? '').slice(0, this.citation().char_start));
  readonly marked = computed(() =>
    (this.text() ?? '').slice(this.citation().char_start, this.citation().char_end),
  );
  readonly after = computed(() => (this.text() ?? '').slice(this.citation().char_end));

  constructor() {
    // A new citation: load its source and jump to the cited page.
    inject(DestroyRef).onDestroy(() => this.setImage(null));
    effect(() => {
      const c = this.citation();
      untracked(() => {
        this.page.set(c.page_start ?? 1);
        void this.load(c);
      });
    });
    // Page changes (pager or new citation) re-render the PDF page.
    effect(() => {
      const page = this.page();
      const count = this.pageCount();
      if (this.isPdf() && count) untracked(() => void this.renderPage(page));
    });
  }

  private async load(c: Citation): Promise<void> {
    this.error.set(null);
    this.loading.set(true);
    try {
      if (this.isPdf()) {
        if (this.pdf?.sourceId !== c.source_id) {
          this.pageCount.set(0);
          const [pdfjs, bytes] = await Promise.all([loadPdfJs(), this.api.fileBytes(c.source_id)]);
          const doc = await pdfjs.getDocument({ data: bytes, useWasm: false }).promise;
          this.pdf = { sourceId: c.source_id, doc };
          this.pageCount.set(doc.numPages);
        } else {
          await this.renderPage(this.page());
        }
      } else {
        this.setImage(null);
        if (c.mime_type?.startsWith('image/')) {
          const bytes = await this.api.fileBytes(c.source_id);
          this.setImage(URL.createObjectURL(new Blob([bytes], { type: c.mime_type })));
        }
        this.text.set(await this.api.text(c.source_id));
        setTimeout(() => this.markEl()?.nativeElement.scrollIntoView({ block: 'center' }));
      }
    } catch (err) {
      this.error.set(`Could not open the source: ${errorMessage(err)}`);
    } finally {
      this.loading.set(false);
    }
  }

  private setImage(url: string | null): void {
    const old = this.imageUrl();
    if (old) URL.revokeObjectURL(old);
    this.imageUrl.set(url);
  }

  private async renderPage(pageNumber: number): Promise<void> {
    const doc = this.pdf?.doc;
    const canvas = this.canvasEl()?.nativeElement;
    if (!doc || !canvas) return;
    this.renderTask?.cancel();
    const page = await doc.getPage(pageNumber);
    const base = page.getViewport({ scale: 1 });
    const available = (this.bodyEl()?.nativeElement.clientWidth ?? 800) - 32;
    const scale = Math.min(2, Math.max(0.5, available / base.width));
    const viewport = page.getViewport({ scale });
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.floor(viewport.width * ratio);
    canvas.height = Math.floor(viewport.height * ratio);
    canvas.style.width = `${viewport.width}px`;
    canvas.style.height = `${viewport.height}px`;
    this.pageSize.set({ width: viewport.width, height: viewport.height });
    // pdfplumber boxes are in PDF points with a top-left origin, like the unrotated viewport.
    this.boxes.set(
      this.citation()
        .bboxes.filter((b) => b.page === pageNumber)
        .map((b) => ({
          left: b.x0 * scale,
          top: b.top * scale,
          width: (b.x1 - b.x0) * scale,
          height: (b.bottom - b.top) * scale,
        })),
    );
    this.renderTask = page.render({
      canvas,
      viewport,
      transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined,
    });
    try {
      await this.renderTask.promise;
    } catch {
      return; // cancelled by a newer render
    }
    const first = this.boxes()[0];
    const body = this.bodyEl()?.nativeElement;
    if (first && body) body.scrollTo({ top: Math.max(0, first.top - 80), behavior: 'smooth' });
  }
}
