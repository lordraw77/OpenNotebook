import { DatePipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatRadioModule } from '@angular/material/radio';

import { AdminApi, ProjectSettingsDto } from '../../core/admin.api';
import { TreeNodeDto } from '../../core/api.models';
import { errorMessage } from '../../core/api.service';
import { hasRole } from './tree';
import { TranslatePipe, t } from '../../core/i18n';

/** Project settings: which providers may process the project's content, and the search index state. */
@Component({
  selector: 'app-project-settings-dialog',
  imports: [
    TranslatePipe,
    DatePipe,
    FormsModule,
    MatButtonModule,
    MatCheckboxModule,
    MatDialogModule,
    MatIconModule,
    MatProgressBarModule,
    MatRadioModule,
  ],
  template: `
    <h2 mat-dialog-title>{{ 'Project settings · {name}' | t: { name: project.name } }}</h2>
    <mat-dialog-content>
      @if (settings(); as s) {
        <h3><mat-icon inline>policy</mat-icon> {{ 'Provider policy' | t }}</h3>
        <p class="muted">
          {{
            'Which model providers may receive this project’s content (documents, questions, images). It applies to every model call: chat, embeddings, OCR, summaries, graph, wiki.'
              | t
          }}
        </p>
        <mat-radio-group [(ngModel)]="mode" [disabled]="!canEdit" class="modes">
          <mat-radio-button value="all">{{ 'All configured providers' | t }}</mat-radio-button>
          <mat-radio-button value="some">{{ 'Only the selected providers' | t }}</mat-radio-button>
        </mat-radio-group>
        @if (mode === 'some') {
          <div class="providers">
            @for (p of s.providers; track p.id) {
              <mat-checkbox
                [checked]="allowed().has(p.id)"
                (change)="toggle(p.id, $event.checked)"
                [disabled]="!canEdit"
              >
                {{ p.name }}
                <span class="muted">({{ p.kind }}{{ p.enabled ? '' : ', disabled' }})</span>
              </mat-checkbox>
            }
          </div>
          @if (allowed().size === 0) {
            <p class="warn">
              {{ 'No provider selected: nothing can be indexed or answered in this project.' | t }}
            </p>
          }
        }
        @if (!canEdit) {
          <p class="muted small">{{ 'Only project owners can change the policy.' | t }}</p>
        }

        <h3><mat-icon inline>database</mat-icon> {{ 'Search index' | t }}</h3>
        <p>
          {{ 'Serving searches:' | t }} <strong>{{ s.index.serving_model ?? '—' }}</strong>
          @if (s.index.switch_pending) {
            <br />{{ 'Configured embedding model:' | t }}
            <strong>{{ s.index.configured_model }}</strong>
          }
        </p>
        @if (s.index.switch_pending) {
          <mat-progress-bar mode="determinate" [value]="progress()"></mat-progress-bar>
          <p class="muted small">
            {{
              '{done} / {total} sources re-indexed with the new model. Searches keep using the current index until all are done, then switch at once. Start or continue with RAG Status → Re-index.'
                | t: { done: s.index.sources_on_configured_model, total: s.index.sources }
            }}
          </p>
        } @else if (s.index.switched_at) {
          <p class="muted small">
            {{ 'Last index switch: {date}' | t: { date: s.index.switched_at | date: 'short' } }}
          </p>
        }
      } @else if (error()) {
        <p class="error-text">{{ error() }}</p>
      } @else {
        <mat-progress-bar mode="indeterminate"></mat-progress-bar>
      }
      @if (error() && settings()) {
        <p class="error-text">{{ error() }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>{{ 'Close' | t }}</button>
      @if (canEdit) {
        <button mat-flat-button (click)="save()" [disabled]="!settings() || saving()">
          {{ 'Save policy' | t }}
        </button>
      }
    </mat-dialog-actions>
  `,
  styles: `
    h3 {
      font: var(--mat-sys-title-small);
      margin: 16px 0 4px;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .modes {
      display: flex;
      flex-direction: column;
    }
    .providers {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
      margin: 4px 0 0 24px;
    }
    .small {
      font-size: 12px;
    }
    .warn {
      color: var(--mat-sys-error);
    }
  `,
})
export class ProjectSettingsDialogComponent {
  protected readonly project = inject<TreeNodeDto>(MAT_DIALOG_DATA);
  private readonly admin = inject(AdminApi);

  readonly settings = signal<ProjectSettingsDto | null>(null);
  readonly allowed = signal<Set<string>>(new Set());
  readonly error = signal<string | null>(null);
  readonly saving = signal(false);
  readonly progress = computed(() => {
    const i = this.settings()?.index;
    return i && i.sources ? (100 * i.sources_on_configured_model) / i.sources : 0;
  });
  protected readonly canEdit = hasRole(this.project, 'owner');
  mode: 'all' | 'some' = 'all';

  constructor() {
    void this.load();
  }

  private async load(): Promise<void> {
    try {
      this.apply(await this.admin.projectSettings(this.project.id));
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }

  private apply(s: ProjectSettingsDto): void {
    this.settings.set(s);
    this.mode = s.restricted ? 'some' : 'all';
    this.allowed.set(new Set(s.providers.filter((p) => p.allowed).map((p) => p.id)));
  }

  toggle(id: string, on: boolean): void {
    const next = new Set(this.allowed());
    if (on) next.add(id);
    else next.delete(id);
    this.allowed.set(next);
  }

  async save(): Promise<void> {
    this.saving.set(true);
    this.error.set(null);
    try {
      this.apply(
        await this.admin.setPolicy(
          this.project.id,
          this.mode === 'all' ? null : [...this.allowed()],
        ),
      );
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.saving.set(false);
    }
  }
}
