import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';

import {
  ModelPhase,
  PHASE_LABELS,
  PhaseAssignment,
  ProviderModel,
  TreeNodeDto,
} from '../../core/api.models';
import { ApiService, errorMessage } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';

interface PhaseEditor {
  phase: ModelPhase;
  assignment: PhaseAssignment;
  candidates: ProviderModel[];
  chain: ProviderModel[];
  dirty: boolean;
}

const PHASE_HELP: Record<ModelPhase, string> = {
  chat: 'Answers in the Workbench. Users can pick any enabled chat model; this chain is the default and the fallback order.',
  summary: 'Source summaries and suggested questions generated after ingestion.',
  graph_extraction: 'Entity and relation extraction for the knowledge graph.',
  vision: 'Descriptions of images and figures.',
  ocr: 'Text extraction from images and scanned pages (OCR models or vision models).',
  embedding:
    'Vectors for semantic search. One model per index, no fallback: changing it requires re-indexing.',
  rerank: 'Optional re-ordering of retrieved passages. Leave empty to disable.',
};

@Component({
  selector: 'app-models',
  imports: [
    FormsModule,
    MatCardModule,
    MatSelectModule,
    MatFormFieldModule,
    MatButtonModule,
    MatIconModule,
    MatTooltipModule,
  ],
  template: `
    <div class="toolbar row">
      <mat-form-field appearance="outline" subscriptSizing="dynamic" class="scope">
        <mat-label>Configure</mat-label>
        <mat-select
          [value]="projectId() ?? GLOBAL"
          (valueChange)="setScope($event === GLOBAL ? null : $event)"
        >
          <mat-option [value]="GLOBAL">Global defaults (all projects)</mat-option>
          @for (p of projects(); track p.id) {
            <mat-option [value]="p.id">Project: {{ p.name }}</mat-option>
          }
        </mat-select>
      </mat-form-field>
      <span class="muted">
        @if (projectId()) {
          A project override replaces the global chain for this project only. Empty override = use
          global defaults.
        } @else {
          Defaults used by every project without its own override.
        }
      </span>
    </div>
    @if (!canEdit()) {
      <p class="muted">
        Read only: {{ projectId() ? 'project owners' : 'administrators' }} can change this
        configuration.
      </p>
    }
    @if (error()) {
      <p class="error-text">{{ error() }}</p>
    }

    <div class="phases">
      @for (e of editors(); track e.phase) {
        <mat-card appearance="outlined">
          <mat-card-header>
            <mat-card-title>{{ labels[e.phase] }}</mat-card-title>
            <mat-card-subtitle>
              @switch (e.assignment.source) {
                @case ('project') {
                  Using project override
                }
                @case ('global') {
                  {{ projectId() ? 'Using global default' : 'Configured' }}
                }
                @default {
                  Not configured
                }
              }
            </mat-card-subtitle>
          </mat-card-header>
          <mat-card-content>
            <p class="muted help">{{ help[e.phase] }}</p>
            <ol class="chain">
              @for (
                m of e.chain;
                track m.id;
                let i = $index;
                let first = $first;
                let last = $last
              ) {
                <li>
                  <span class="model">
                    <strong>{{ m.provider_name }}</strong> / {{ m.model }}
                    @if (m.embedding_dim) {
                      <span class="cap">dim {{ m.embedding_dim }}</span>
                    }
                    @if (!m.available) {
                      <span class="cap warn" matTooltip="No longer listed by the provider"
                        >unavailable</span
                      >
                    }
                  </span>
                  @if (canEdit()) {
                    <button
                      mat-icon-button
                      [disabled]="first"
                      (click)="move(e, i, -1)"
                      aria-label="Move up"
                    >
                      <mat-icon>arrow_upward</mat-icon>
                    </button>
                    <button
                      mat-icon-button
                      [disabled]="last"
                      (click)="move(e, i, 1)"
                      aria-label="Move down"
                    >
                      <mat-icon>arrow_downward</mat-icon>
                    </button>
                    <button mat-icon-button (click)="removeAt(e, i)" aria-label="Remove">
                      <mat-icon>close</mat-icon>
                    </button>
                  }
                </li>
              } @empty {
                <li class="muted none">
                  {{
                    projectId() ? 'No override: the global chain applies.' : 'No model selected.'
                  }}
                </li>
              }
            </ol>
            @if (canEdit() && (!e.assignment.single_model || e.chain.length === 0)) {
              <mat-form-field appearance="outline" subscriptSizing="dynamic" class="add">
                <mat-label>{{ e.chain.length ? 'Add fallback model' : 'Select model' }}</mat-label>
                <mat-select (valueChange)="add(e, $event)" [value]="null">
                  @for (m of available(e); track m.id) {
                    <mat-option [value]="m">{{ m.provider_name }} / {{ m.model }}</mat-option>
                  } @empty {
                    <mat-option disabled
                      >No enabled model with this capability (Settings → Providers)</mat-option
                    >
                  }
                </mat-select>
              </mat-form-field>
            }
            @if (e.phase === 'embedding' && e.dirty) {
              <p class="warn-text">
                <mat-icon>warning</mat-icon> Sources already indexed with another embedding model
                must be re-indexed.
              </p>
            }
          </mat-card-content>
          @if (canEdit()) {
            <mat-card-actions align="end">
              <button mat-button [disabled]="!e.dirty" (click)="reset()">Discard</button>
              <button mat-flat-button [disabled]="!e.dirty" (click)="save(e)">Save</button>
            </mat-card-actions>
          }
        </mat-card>
      }
    </div>
  `,
  styles: `
    .toolbar {
      margin: 16px 0 8px;
    }
    .scope {
      width: min(360px, 100%);
    }
    .phases {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(min(420px, 100%), 1fr));
      gap: 16px;
      margin-top: 8px;
    }
    .help {
      margin: 8px 0;
    }
    .chain {
      padding-left: 20px;
      margin: 8px 0;
    }
    .chain li {
      display: flex;
      align-items: center;
      gap: 2px;
      min-height: 40px;
    }
    .chain li::marker {
      color: var(--mat-sys-primary);
    }
    .chain li.none {
      display: list-item;
    }
    .model {
      flex: 1;
      min-width: 0;
      overflow-wrap: anywhere;
    }
    .add {
      width: 100%;
    }
    .cap.warn {
      background: var(--mat-sys-error-container);
      color: var(--mat-sys-on-error-container);
    }
    .warn-text {
      display: flex;
      gap: 6px;
      align-items: center;
      color: var(--mat-sys-error);
    }
  `,
})
export class ModelsComponent {
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly snack = inject(MatSnackBar);

  protected readonly GLOBAL = '__global__';
  protected readonly labels = PHASE_LABELS;
  protected readonly help = PHASE_HELP;

  readonly projects = signal<TreeNodeDto[]>([]);
  readonly projectId = signal<string | null>(null);
  readonly editors = signal<PhaseEditor[]>([]);
  readonly error = signal<string | null>(null);
  readonly canEdit = computed(() => {
    const pid = this.projectId();
    if (this.auth.isAdmin()) return true;
    return pid !== null && this.projects().find((p) => p.id === pid)?.role === 'owner';
  });

  constructor() {
    void this.api
      .nodes()
      .then((n) => this.projects.set(n.filter((x) => x.kind === 'project' && x.role !== null)));
    void this.reset();
  }

  setScope(projectId: string | null): void {
    this.projectId.set(projectId);
    void this.reset();
  }

  async reset(): Promise<void> {
    this.error.set(null);
    const pid = this.projectId();
    try {
      const assignments = await this.api.assignments(pid);
      const editors = await Promise.all(
        assignments.map(async (a) => ({
          phase: a.phase,
          assignment: a,
          candidates: await this.api.selectableModels(a.phase, pid, true),
          chain: (pid ? (a.project_chain ?? []) : a.global_chain).map((c) => c.model),
          dirty: false,
        })),
      );
      this.editors.set(editors);
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }

  available(e: PhaseEditor): ProviderModel[] {
    const used = new Set(e.chain.map((m) => m.id));
    return e.candidates.filter((m) => !used.has(m.id));
  }

  add(e: PhaseEditor, m: ProviderModel | null): void {
    if (m) this.update(e, [...e.chain, m]);
  }

  removeAt(e: PhaseEditor, i: number): void {
    this.update(
      e,
      e.chain.filter((_, idx) => idx !== i),
    );
  }

  move(e: PhaseEditor, i: number, delta: number): void {
    const chain = [...e.chain];
    [chain[i], chain[i + delta]] = [chain[i + delta], chain[i]];
    this.update(e, chain);
  }

  private update(e: PhaseEditor, chain: ProviderModel[]): void {
    this.editors.update((list) =>
      list.map((x) => (x.phase === e.phase ? { ...x, chain, dirty: true } : x)),
    );
  }

  async save(e: PhaseEditor): Promise<void> {
    try {
      await this.api.putAssignment(
        e.phase,
        e.chain.map((m) => m.id),
        this.projectId(),
      );
      this.snack.open(`${PHASE_LABELS[e.phase]} saved`, 'Close', { duration: 3000 });
      await this.reset();
    } catch (err) {
      this.snack.open(errorMessage(err), 'Close', { duration: 6000 });
    }
  }
}
