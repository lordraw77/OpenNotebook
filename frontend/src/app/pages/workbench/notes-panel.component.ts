import { DatePipe } from '@angular/common';
import { Component, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';

import { errorMessage } from '../../core/api.service';
import { Citation, NoteDto, SourcesApi } from '../../core/sources.api';
import { AnswerViewComponent } from './answer-view.component';

interface Draft {
  id: string | null;
  title: string;
  body_md: string;
  indexed: boolean;
}

/** Notes of the selected notebook; an indexed note is searchable like any source. */
@Component({
  selector: 'app-notes-panel',
  imports: [
    DatePipe,
    FormsModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatSlideToggleModule,
    MatCheckboxModule,
    MatTooltipModule,
    AnswerViewComponent,
  ],
  template: `
    @if (!notebookId()) {
      <p class="muted pad">Select a notebook to see and write its notes.</p>
    } @else {
      @if (canEdit() && !draft()) {
        <div class="pad">
          <button mat-stroked-button (click)="edit(null)"><mat-icon>add</mat-icon> New note</button>
        </div>
      }
      @if (draft(); as d) {
        <form class="editor pad" (ngSubmit)="save(d)">
          <mat-form-field appearance="outline" subscriptSizing="dynamic">
            <mat-label>Title</mat-label>
            <input matInput name="title" [(ngModel)]="d.title" maxlength="300" required />
          </mat-form-field>
          <mat-form-field appearance="outline" subscriptSizing="dynamic">
            <mat-label>Note (Markdown)</mat-label>
            <textarea matInput name="body" [(ngModel)]="d.body_md" rows="8"></textarea>
          </mat-form-field>
          <mat-checkbox name="indexed" [(ngModel)]="d.indexed"
            >Index as source (searchable)</mat-checkbox
          >
          <div class="row">
            <button mat-button type="button" (click)="draft.set(null)">Cancel</button>
            <button mat-flat-button type="submit" [disabled]="!d.title.trim()">Save</button>
          </div>
        </form>
      }
      @for (n of notes(); track n.id) {
        <article class="note">
          <header>
            <strong>{{ n.title }}</strong>
            <span class="spacer"></span>
            @if (n.indexed) {
              <span class="cap" [matTooltip]="'Index status: ' + (n.source_status ?? 'pending')">{{
                n.source_status ?? 'queued'
              }}</span>
            }
            @if (canEdit()) {
              <button mat-icon-button aria-label="Edit note" (click)="edit(n)">
                <mat-icon>edit</mat-icon>
              </button>
              <button mat-icon-button aria-label="Delete note" (click)="remove(n)">
                <mat-icon>delete</mat-icon>
              </button>
            }
          </header>
          @if (n.origin === 'chat') {
            <app-answer-view
              class="body"
              [content]="n.body_md"
              [citations]="n.citations"
              (cite)="openCitation.emit($event)"
            />
          } @else {
            <p class="body">{{ n.body_md }}</p>
          }
          <div class="muted meta">
            {{ n.updated_at | date: 'short' }}{{ n.origin === 'chat' ? ' · from chat' : '' }}
          </div>
        </article>
      } @empty {
        @if (!draft()) {
          <p class="muted pad">No notes in this notebook yet.</p>
        }
      }
    }
  `,
  styles: `
    :host {
      display: block;
    }
    .pad {
      padding: 0 16px 12px;
    }
    .editor {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .row {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
    }
    .note {
      margin: 0 12px 10px;
      padding: 8px 12px;
      border: 1px solid var(--mat-sys-outline-variant);
      border-radius: 12px;
    }
    .note header {
      display: flex;
      align-items: center;
      gap: 4px;
    }
    .spacer {
      flex: 1;
    }
    p.body {
      white-space: pre-wrap;
    }
    .body {
      margin: 4px 0;
      max-height: 12em;
      overflow: auto;
    }
    .meta {
      font-size: 12px;
    }
  `,
})
export class NotesPanelComponent {
  private readonly api = inject(SourcesApi);
  private readonly snack = inject(MatSnackBar);

  readonly notebookId = input<string | null>(null);
  readonly canEdit = input(false);
  /** Bump to reload (e.g. while indexed notes are being processed). */
  readonly refresh = input(0);
  readonly changed = output<void>();
  readonly openCitation = output<Citation>();

  readonly notes = signal<NoteDto[]>([]);
  readonly draft = signal<Draft | null>(null);

  private shownNotebook: string | null = null;

  constructor() {
    effect(() => {
      this.refresh();
      const id = this.notebookId();
      if (id !== this.shownNotebook) {
        this.shownNotebook = id;
        this.draft.set(null); // keep an open draft across periodic refreshes of the same notebook
      }
      void this.load(id);
    });
  }

  private async load(id: string | null): Promise<void> {
    this.notes.set(id ? await this.api.notes(id) : []);
  }

  edit(n: NoteDto | null): void {
    this.draft.set(
      n
        ? { id: n.id, title: n.title, body_md: n.body_md, indexed: n.indexed }
        : { id: null, title: '', body_md: '', indexed: true },
    );
  }

  async save(d: Draft): Promise<void> {
    const nb = this.notebookId();
    if (!nb) return;
    try {
      const body = { title: d.title.trim(), body_md: d.body_md, indexed: d.indexed };
      await (d.id ? this.api.updateNote(d.id, body) : this.api.createNote(nb, body));
      this.draft.set(null);
      await this.load(nb);
      this.changed.emit();
    } catch (err) {
      this.snack.open(errorMessage(err), 'Close', { duration: 5000 });
    }
  }

  async remove(n: NoteDto): Promise<void> {
    if (!confirm(`Delete note “${n.title}”?`)) return;
    try {
      await this.api.deleteNote(n.id);
      await this.load(this.notebookId());
      this.changed.emit();
    } catch (err) {
      this.snack.open(errorMessage(err), 'Close', { duration: 5000 });
    }
  }
}
