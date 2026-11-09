import { DatePipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatMenuModule } from '@angular/material/menu';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';

import {
  BASE_CAPABILITIES,
  ModelPhase,
  ModelTestResult,
  Provider,
  ProviderKindInfo,
  ProviderModel,
} from '../../core/api.models';
import { ApiService, errorMessage } from '../../core/api.service';
import { TranslatePipe, t } from '../../core/i18n';

interface NewProvider {
  kind: string;
  name: string;
  api_key: string;
  base_url: string;
  options: Record<string, string>;
  timeout_s: number;
}

@Component({
  selector: 'app-providers',
  imports: [
    TranslatePipe,
    DatePipe,
    FormsModule,
    MatCardModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatSlideToggleModule,
    MatCheckboxModule,
    MatMenuModule,
    MatTooltipModule,
    MatProgressBarModule,
  ],
  templateUrl: './providers.component.html',
  styles: `
    .section {
      font: var(--mat-sys-title-medium);
      margin: 24px 0 8px;
    }
    table {
      width: 100%;
    }
    .table-wrap {
      overflow-x: auto;
    }
    tr.selected {
      background: var(--mat-sys-secondary-container);
    }
    tr.clickable {
      cursor: pointer;
    }
    .form {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: baseline;
    }
    .form mat-form-field {
      width: min(260px, 100%);
    }
    .filters {
      margin: 8px 0;
    }
    .filters .grow {
      flex: 1;
      min-width: 200px;
    }
    .test-ok {
      color: var(--mat-sys-primary);
    }
    .model-id {
      overflow-wrap: anywhere;
    }
    .cap.off {
      opacity: 0.4;
    }
  `,
})
export class ProvidersComponent {
  private readonly api = inject(ApiService);
  private readonly snack = inject(MatSnackBar);

  protected readonly allCaps = BASE_CAPABILITIES;
  readonly kinds = signal<ProviderKindInfo[]>([]);
  readonly providers = signal<Provider[]>([]);
  readonly selectedId = signal<string | null>(null);
  readonly selected = computed(
    () => this.providers().find((p) => p.id === this.selectedId()) ?? null,
  );
  readonly models = signal<ProviderModel[]>([]);
  readonly busy = signal(false);
  readonly tests = signal<Record<string, ModelTestResult | 'running'>>({});
  readonly showAdd = signal(false);

  capability: ModelPhase | null = null;
  query = '';
  enabledOnly = false;
  newKey = '';
  manualModel = '';
  manualCaps: ModelPhase[] = ['embedding'];
  draft: NewProvider = this.emptyDraft();

  readonly providerColumns = ['name', 'kind', 'key', 'models', 'sync', 'enabled', 'actions'];
  readonly modelColumns = ['enabled', 'model', 'capabilities', 'context', 'test'];

  readonly draftKind = computed(() => this.kinds().find((k) => k.kind === this.draftKindSig()));
  private readonly draftKindSig = signal<string>('');

  constructor() {
    void this.api.providerKinds().then((k) => this.kinds.set(k));
    void this.load();
  }

  private emptyDraft(): NewProvider {
    return { kind: '', name: '', api_key: '', base_url: '', options: {}, timeout_s: 60 };
  }

  setDraftKind(kind: string): void {
    this.draft = {
      ...this.emptyDraft(),
      kind,
      name: kind,
      timeout_s: kind === 'ollama' ? 600 : 60,
    };
    this.draftKindSig.set(kind);
  }

  async load(): Promise<void> {
    try {
      this.providers.set(await this.api.providers());
      if (this.selectedId()) await this.loadModels();
    } catch (err) {
      this.toast(errorMessage(err));
    }
  }

  async select(p: Provider): Promise<void> {
    this.selectedId.set(p.id);
    this.newKey = '';
    await this.loadModels();
  }

  async loadModels(): Promise<void> {
    const id = this.selectedId();
    if (!id) return;
    this.models.set(
      await this.api.providerModels(id, {
        capability: this.capability,
        q: this.query,
        enabled_only: this.enabledOnly,
      }),
    );
  }

  async create(): Promise<void> {
    const kind = this.draftKind();
    if (!kind) return;
    await this.task(async () => {
      const p = await this.api.createProvider({
        kind: this.draft.kind,
        name: this.draft.name,
        api_key: this.draft.api_key || null,
        base_url: this.draft.base_url || null,
        options: this.draft.options,
        timeout_s: this.draft.timeout_s,
      });
      this.showAdd.set(false);
      this.draft = this.emptyDraft();
      this.draftKindSig.set('');
      await this.load();
      await this.select(p);
      await this.sync(p);
    }, t('Provider added'));
  }

  async sync(p: Provider): Promise<void> {
    await this.task(async () => {
      const r = await this.api.syncProvider(p.id);
      this.toast(
        t('{name}: {n} models ({added} new, {gone} no longer listed)', {
          name: p.name,
          n: r.discovered,
          added: r.added,
          gone: r.unavailable,
        }),
      );
      await this.load();
    });
  }

  async setEnabled(p: Provider, enabled: boolean): Promise<void> {
    await this.task(
      () => this.api.updateProvider(p.id, { enabled }).then(() => this.load()),
      enabled ? t('Enabled') : t('Disabled'),
    );
  }

  async saveKey(p: Provider): Promise<void> {
    await this.task(async () => {
      await this.api.updateProvider(p.id, { api_key: this.newKey });
      this.newKey = '';
      await this.load();
    }, t('API key updated'));
  }

  async remove(p: Provider): Promise<void> {
    if (!confirm(t('Remove provider “{name}” and its model catalog?', { name: p.name }))) return;
    await this.task(async () => {
      await this.api.deleteProvider(p.id);
      if (this.selectedId() === p.id) {
        this.selectedId.set(null);
        this.models.set([]);
      }
      await this.load();
    }, t('Provider removed'));
  }

  async toggleModel(m: ProviderModel, enabled: boolean): Promise<void> {
    await this.task(async () => {
      await this.api.updateModel(m.id, { enabled });
      await this.load();
    });
  }

  async toggleCap(m: ProviderModel, cap: ModelPhase): Promise<void> {
    const caps = m.capabilities.includes(cap)
      ? m.capabilities.filter((c) => c !== cap)
      : [...m.capabilities, cap];
    await this.task(async () => {
      await this.api.updateModel(m.id, { capabilities: caps });
      await this.loadModels();
    });
  }

  async addManual(): Promise<void> {
    const id = this.selectedId();
    if (!id || !this.manualModel.trim()) return;
    await this.task(async () => {
      await this.api.addModel(id, {
        model: this.manualModel.trim(),
        capabilities: this.manualCaps,
      });
      this.manualModel = '';
      await this.load();
    }, t('Model added'));
  }

  async test(m: ProviderModel): Promise<void> {
    this.tests.update((t) => ({ ...t, [m.id]: 'running' }));
    try {
      const r = await this.api.testModel(m.id);
      this.tests.update((t) => ({ ...t, [m.id]: r }));
      if (!r.ok && (r.status_code === 404 || r.status_code === 410)) await this.loadModels();
    } catch (err) {
      this.tests.update((t) => ({ ...t, [m.id]: { ok: false, error: errorMessage(err) } }));
    }
  }

  testResult(m: ProviderModel): ModelTestResult | 'running' | undefined {
    return this.tests()[m.id];
  }

  isResult(v: ModelTestResult | 'running' | undefined): v is ModelTestResult {
    return typeof v === 'object';
  }

  private async task(fn: () => Promise<unknown>, ok?: string): Promise<void> {
    this.busy.set(true);
    try {
      await fn();
      if (ok) this.toast(ok);
    } catch (err) {
      this.toast(errorMessage(err));
    } finally {
      this.busy.set(false);
    }
  }

  private toast(msg: string): void {
    this.snack.open(msg, t('Close'), { duration: 5000 });
  }
}
