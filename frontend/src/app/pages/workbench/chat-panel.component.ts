import { DecimalPipe } from '@angular/common';
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
import { TextFieldModule } from '@angular/cdk/text-field';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatMenuModule } from '@angular/material/menu';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';

import { errorMessage } from '../../core/api.service';
import { Attempt, ChatApi, ChatEvent, ConversationDto, MessageDto } from '../../core/chat.api';
import { Citation, SourcesApi, citationLocation } from '../../core/sources.api';
import { AnswerViewComponent } from './answer-view.component';

interface Pending {
  question: string;
  stage: 'retrieving' | 'generating' | 'answering';
  context: Citation[];
  content: string;
  model: string | null;
  attempts: Attempt[];
}

export interface NotebookOption {
  id: string;
  name: string;
}

/** Grounded chat over the selected scope: streaming answers with clickable, validated citations. */
@Component({
  selector: 'app-chat-panel',
  imports: [
    DecimalPipe,
    FormsModule,
    TextFieldModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatMenuModule,
    MatProgressBarModule,
    MatSelectModule,
    MatTooltipModule,
    AnswerViewComponent,
  ],
  template: `
    <div class="bar">
      <mat-form-field appearance="outline" class="conv" subscriptSizing="dynamic">
        <mat-label>Conversation</mat-label>
        <mat-select
          [value]="conversationId()"
          (valueChange)="openConversation($event)"
          [disabled]="!scopeId() || streaming()"
        >
          <mat-option [value]="null"><mat-icon>add_comment</mat-icon> New chat</mat-option>
          @for (c of conversations(); track c.id) {
            <mat-option [value]="c.id">{{ c.title }}</mat-option>
          }
        </mat-select>
      </mat-form-field>
      @if (conversationId()) {
        <button
          mat-icon-button
          [matMenuTriggerFor]="convMenu"
          aria-label="Conversation actions"
          [disabled]="streaming()"
        >
          <mat-icon>more_vert</mat-icon>
        </button>
        <mat-menu #convMenu="matMenu">
          <button mat-menu-item (click)="renameConversation()">
            <mat-icon>edit</mat-icon> Rename
          </button>
          <button mat-menu-item (click)="deleteConversation()">
            <mat-icon>delete</mat-icon> Delete
          </button>
        </mat-menu>
      }
    </div>

    <div class="thread" #thread>
      @if (!scopeId()) {
        <div class="placeholder">
          <mat-icon>forum</mat-icon>
          <p>Select a project, workspace or notebook in the tree to chat with its sources.</p>
        </div>
      } @else if (messages().length === 0 && !pending()) {
        <div class="placeholder">
          <mat-icon>auto_awesome</mat-icon>
          <p>Ask a question about the active sources in this scope.</p>
          <p class="muted">
            Answers use only these sources, and every statement links to the passage it comes from.
          </p>
        </div>
      }

      @for (m of messages(); track m.id) {
        @if (m.role === 'user') {
          <div class="q">{{ m.content }}</div>
        } @else {
          <article class="a" [class.failed]="m.status === 'error'">
            <app-answer-view
              [content]="m.content"
              [citations]="m.context"
              (cite)="openCitation.emit($event)"
            />
            @if (m.status === 'error') {
              <p class="error-text"><mat-icon inline>error</mat-icon> {{ m.error }}</p>
            } @else if (m.status === 'stopped') {
              <p class="muted small"><mat-icon inline>stop_circle</mat-icon> Stopped</p>
            }
            @if (m.citations.length) {
              <div class="sources">
                @for (c of m.citations; track c.n) {
                  <button type="button" class="src" (click)="openCitation.emit(c)">
                    <span class="n">{{ c.n }}</span>
                    <span class="t">{{ c.source_title }}</span>
                    @if (loc(c)) {
                      <span class="muted">{{ loc(c) }}</span>
                    }
                  </button>
                }
              </div>
            }
            @if (warnings(m).length) {
              <ul class="checks">
                @for (w of warnings(m); track w) {
                  <li><mat-icon inline>info</mat-icon> {{ w }}</li>
                }
              </ul>
            }
            <footer class="meta">
              @if (m.model_label) {
                <span class="model" [matTooltip]="attemptsText(m.attempts)">
                  <mat-icon inline>smart_toy</mat-icon> {{ m.model_label }}
                  @if (fallbacks(m.attempts)) {
                    <span class="fallback">fallback</span>
                  }
                </span>
              }
              @if (m.latency_ms) {
                <span class="muted">{{ m.latency_ms / 1000 | number: '1.1-1' }} s</span>
              }
              <span class="spacer"></span>
              <button
                mat-icon-button
                matTooltip="Copy"
                aria-label="Copy answer"
                (click)="copy(m.content)"
              >
                <mat-icon>content_copy</mat-icon>
              </button>
              @if (m.status === 'complete' && notebooks().length) {
                @if (notebooks().length === 1) {
                  <button
                    mat-icon-button
                    [matTooltip]="'Save as note in ' + notebooks()[0].name"
                    aria-label="Save as note"
                    (click)="saveNote(m, notebooks()[0].id)"
                  >
                    <mat-icon>note_add</mat-icon>
                  </button>
                } @else {
                  <button
                    mat-icon-button
                    matTooltip="Save as note"
                    aria-label="Save as note"
                    [matMenuTriggerFor]="nbMenu"
                  >
                    <mat-icon>note_add</mat-icon>
                  </button>
                  <mat-menu #nbMenu="matMenu">
                    @for (nb of notebooks(); track nb.id) {
                      <button mat-menu-item (click)="saveNote(m, nb.id)">
                        <mat-icon>book_2</mat-icon> {{ nb.name }}
                      </button>
                    }
                  </mat-menu>
                }
              }
            </footer>
          </article>
        }
      }

      @if (pending(); as p) {
        @if (p.question) {
          <div class="q">{{ p.question }}</div>
        }
        <article class="a">
          @if (p.stage !== 'answering') {
            <div class="stage muted">
              <mat-progress-bar mode="indeterminate"></mat-progress-bar>
              {{
                p.stage === 'retrieving'
                  ? 'Searching the sources…'
                  : 'Reading ' + p.context.length + ' passages…'
              }}
            </div>
          }
          <app-answer-view
            [content]="p.content"
            [citations]="p.context"
            [streaming]="p.stage === 'answering'"
            (cite)="openCitation.emit($event)"
          />
          @if (p.model) {
            <footer class="meta">
              <span class="model" [matTooltip]="attemptsText(p.attempts)">
                <mat-icon inline>smart_toy</mat-icon> {{ p.model }}
                @if (fallbacks(p.attempts)) {
                  <span class="fallback">fallback</span>
                }
              </span>
            </footer>
          }
        </article>
      }
      @if (error()) {
        <p class="error-text">{{ error() }}</p>
      }
    </div>

    <form class="composer" (ngSubmit)="send()">
      <mat-form-field appearance="outline" class="grow" subscriptSizing="dynamic">
        <mat-label>{{ scopeId() ? 'Ask the sources in scope' : 'Select a scope first' }}</mat-label>
        <textarea
          matInput
          name="q"
          [(ngModel)]="question"
          [disabled]="!scopeId()"
          maxlength="8000"
          rows="1"
          cdkTextareaAutosize
          (keydown.enter)="onEnter($event)"
        ></textarea>
      </mat-form-field>
      @if (streaming()) {
        <button mat-stroked-button type="button" (click)="stop()">
          <mat-icon>stop</mat-icon> Stop
        </button>
      } @else {
        <button mat-flat-button type="submit" [disabled]="!scopeId() || !question.trim()">
          <mat-icon>send</mat-icon> Ask
        </button>
      }
    </form>
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      flex: 1;
      min-height: 0;
    }
    .bar {
      display: flex;
      align-items: center;
      gap: 4px;
      padding: 8px 16px 0;
    }
    .conv {
      flex: 1;
      max-width: 420px;
    }
    .thread {
      flex: 1;
      overflow: auto;
      padding: 12px 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .placeholder {
      text-align: center;
      margin: 12vh auto 0;
      max-width: 440px;
    }
    .placeholder mat-icon {
      font-size: 48px;
      width: 48px;
      height: 48px;
      color: var(--mat-sys-primary);
    }
    .q {
      align-self: flex-end;
      max-width: 80%;
      padding: 10px 14px;
      border-radius: 18px 18px 4px 18px;
      background: var(--mat-sys-primary-container);
      color: var(--mat-sys-on-primary-container);
      white-space: pre-wrap;
    }
    .a {
      max-width: 92%;
      padding: 12px 16px 4px;
      border-radius: 4px 18px 18px 18px;
      background: var(--mat-sys-surface-container);
      border: 1px solid var(--mat-sys-outline-variant);
    }
    .a.failed {
      border-color: var(--mat-sys-error);
    }
    .stage {
      font-size: 13px;
      margin-bottom: 8px;
    }
    .stage mat-progress-bar {
      margin-bottom: 6px;
    }
    .sources {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin: 4px 0 6px;
    }
    .src {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      max-width: 100%;
      padding: 3px 10px 3px 3px;
      border: 1px solid var(--mat-sys-outline-variant);
      border-radius: 14px;
      background: var(--mat-sys-surface-container-low);
      color: var(--mat-sys-on-surface);
      font: var(--mat-sys-label-medium);
      cursor: pointer;
    }
    .src:hover {
      border-color: var(--mat-sys-primary);
    }
    .src .n {
      display: grid;
      place-items: center;
      min-width: 20px;
      height: 20px;
      border-radius: 10px;
      background: var(--mat-sys-primary-container);
      color: var(--mat-sys-on-primary-container);
      font-weight: 600;
      font-size: 11px;
    }
    .src .t {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      max-width: 220px;
    }
    .checks {
      list-style: none;
      padding: 0;
      margin: 4px 0;
      font-size: 12px;
      color: var(--mat-sys-on-surface-variant);
    }
    .meta {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      color: var(--mat-sys-on-surface-variant);
    }
    .model {
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .fallback {
      padding: 0 6px;
      border-radius: 8px;
      background: var(--mat-sys-tertiary-container);
      color: var(--mat-sys-on-tertiary-container);
    }
    .spacer {
      flex: 1;
    }
    .small {
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
    textarea {
      max-height: 160px;
    }
  `,
})
export class ChatPanelComponent {
  private readonly api = inject(ChatApi);
  private readonly sources = inject(SourcesApi);
  private readonly snack = inject(MatSnackBar);

  readonly scopeId = input<string | null>(null);
  readonly modelId = input<string | null>(null);
  /** Notebooks in scope where the user may write notes (targets of "Save as note"). */
  readonly notebooks = input<NotebookOption[]>([]);
  readonly openCitation = output<Citation>();
  readonly noteSaved = output<void>();

  private readonly threadEl = viewChild<ElementRef<HTMLElement>>('thread');

  readonly conversations = signal<ConversationDto[]>([]);
  readonly conversationId = signal<string | null>(null);
  readonly messages = signal<MessageDto[]>([]);
  readonly pending = signal<Pending | null>(null);
  readonly error = signal<string | null>(null);
  readonly streaming = computed(() => this.pending() !== null);
  question = '';
  private abort: AbortController | null = null;

  protected readonly loc = citationLocation;

  constructor() {
    effect(() => {
      const scope = this.scopeId();
      untracked(() => void this.loadScope(scope));
    });
    inject(DestroyRef).onDestroy(() => this.abort?.abort());
  }

  private async loadScope(scope: string | null): Promise<void> {
    this.abort?.abort();
    this.pending.set(null);
    this.error.set(null);
    this.conversationId.set(null);
    this.messages.set([]);
    this.conversations.set([]);
    if (!scope) return;
    try {
      const list = await this.api.list(scope);
      if (this.scopeId() !== scope) return;
      this.conversations.set(list);
      if (list.length) await this.openConversation(list[0].id);
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }

  async openConversation(id: string | null): Promise<void> {
    this.conversationId.set(id);
    this.error.set(null);
    if (!id) {
      this.messages.set([]);
      return;
    }
    try {
      const conv = await this.api.get(id);
      this.messages.set(conv.messages);
      this.scrollToEnd();
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }

  onEnter(event: Event): void {
    const e = event as KeyboardEvent;
    if (e.shiftKey || e.isComposing) return;
    e.preventDefault();
    if (!this.streaming()) void this.send();
  }

  async send(): Promise<void> {
    const scope = this.scopeId();
    const question = this.question.trim();
    if (!scope || !question || this.streaming()) return;
    this.error.set(null);
    this.question = '';
    this.pending.set({
      question,
      stage: 'retrieving',
      context: [],
      content: '',
      model: null,
      attempts: [],
    });
    this.scrollToEnd();
    this.abort = new AbortController();
    try {
      let convId = this.conversationId();
      if (!convId) {
        const conv = await this.api.create(scope);
        convId = conv.id;
        this.conversationId.set(conv.id);
        this.conversations.update((list) => [conv, ...list]);
      }
      await this.api.ask(
        convId,
        question,
        this.modelId(),
        (e) => this.onEvent(e),
        this.abort.signal,
      );
    } catch (err) {
      if ((err as Error).name !== 'AbortError') this.error.set(errorMessage(err));
    } finally {
      this.abort = null;
      this.pending.set(null);
      await this.refreshConversation();
    }
  }

  stop(): void {
    this.abort?.abort();
  }

  private onEvent(e: ChatEvent): void {
    const p = this.pending();
    if (!p) return;
    switch (e.event) {
      case 'message':
        this.messages.update((list) => [...list, e.data]);
        this.pending.set({ ...p, question: '' });
        break;
      case 'status':
        this.pending.set({ ...p, stage: e.data.stage });
        break;
      case 'sources':
        this.pending.set({ ...p, context: e.data.context });
        break;
      case 'provider':
        this.pending.set({ ...p, model: e.data.model, attempts: e.data.attempts });
        break;
      case 'token':
        this.pending.set({ ...p, stage: 'answering', content: p.content + e.data.text });
        this.scrollToEnd(true);
        break;
      case 'done':
        this.messages.update((list) => [...list, e.data]);
        this.pending.set(null);
        break;
      case 'error':
        // the stored assistant message (event "done") carries the error
        break;
    }
  }

  /** Reload the stored turns (also after a stop, when "done" never arrived) and the title. */
  private async refreshConversation(): Promise<void> {
    const id = this.conversationId();
    if (!id) return;
    try {
      const conv = await this.api.get(id);
      this.messages.set(conv.messages);
      this.conversations.update((list) =>
        list.map((c) => (c.id === id ? { ...c, title: conv.title } : c)),
      );
      this.scrollToEnd();
    } catch {
      // keep what is shown
    }
  }

  async renameConversation(): Promise<void> {
    const id = this.conversationId();
    const current = this.conversations().find((c) => c.id === id);
    const title = prompt('Conversation title', current?.title ?? '')?.trim();
    if (!id || !title) return;
    try {
      const conv = await this.api.rename(id, title);
      this.conversations.update((list) => list.map((c) => (c.id === id ? conv : c)));
    } catch (err) {
      this.toast(errorMessage(err));
    }
  }

  async deleteConversation(): Promise<void> {
    const id = this.conversationId();
    if (!id || !confirm('Delete this conversation?')) return;
    try {
      await this.api.remove(id);
      this.conversations.update((list) => list.filter((c) => c.id !== id));
      await this.openConversation(null);
    } catch (err) {
      this.toast(errorMessage(err));
    }
  }

  async saveNote(m: MessageDto, notebookId: string): Promise<void> {
    const list = this.messages();
    const question = list[list.indexOf(m) - 1];
    const title = (question?.role === 'user' ? question.content : 'Chat answer')
      .split('\n')[0]
      .slice(0, 120);
    try {
      await this.sources.createNote(notebookId, {
        title,
        body_md: '',
        indexed: false,
        from_message_id: m.id,
      });
      this.toast('Saved as note');
      this.noteSaved.emit();
    } catch (err) {
      this.toast(errorMessage(err));
    }
  }

  async copy(text: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      this.toast('Copied');
    } catch {
      this.toast('Copy is not available in this browser context');
    }
  }

  protected warnings(m: MessageDto): string[] {
    const out: string[] = [];
    const c = m.checks ?? {};
    if (c.uncited_sentences)
      out.push(
        `${c.uncited_sentences} ${c.uncited_sentences === 1 ? 'sentence has' : 'sentences have'} no citation`,
      );
    if (c.invalid_citations?.length)
      out.push(
        `Removed citations to passages that were not provided: ${c.invalid_citations.join(', ')}`,
      );
    for (const w of c.warnings ?? []) out.push(w);
    return out;
  }

  protected fallbacks(attempts: Attempt[]): boolean {
    return attempts.some((a) => a.error);
  }

  protected attemptsText(attempts: Attempt[]): string {
    return attempts
      .map((a) => (a.error ? `${a.model}: failed (${a.error})` : `${a.model}: answered`))
      .join('\n');
  }

  private scrollToEnd(onlyIfNear = false): void {
    setTimeout(() => {
      const el = this.threadEl()?.nativeElement;
      if (!el) return;
      if (onlyIfNear && el.scrollHeight - el.scrollTop - el.clientHeight > 160) return;
      el.scrollTop = el.scrollHeight;
    });
  }

  private toast(message: string): void {
    this.snack.open(message, 'Close', { duration: 4000 });
  }
}
