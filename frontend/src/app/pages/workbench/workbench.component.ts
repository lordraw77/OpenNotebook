import { NgTemplateOutlet } from '@angular/common';
import { Component, DestroyRef, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatDialog } from '@angular/material/dialog';
import { MatDividerModule } from '@angular/material/divider';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatMenuModule } from '@angular/material/menu';
import { MatSelectModule } from '@angular/material/select';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatTreeModule } from '@angular/material/tree';
import { RouterLink } from '@angular/router';

import { NodeKind, ProviderModel, TreeNodeDto } from '../../core/api.models';
import { ApiService, errorMessage } from '../../core/api.service';
import { Citation, SourceDto, SourcesApi, TERMINAL } from '../../core/sources.api';
import { ChatPanelComponent, NotebookOption } from './chat-panel.component';
import { NameDialogComponent, ShareDialogComponent } from './dialogs';
import { NotesPanelComponent } from './notes-panel.component';
import { SearchPanelComponent } from './search-panel.component';
import { SourceDetailComponent } from './source-detail.component';
import { SourceViewerComponent } from './source-viewer.component';
import {
  CHILD_KINDS,
  KIND_ICONS,
  SOURCE_ICONS,
  TreeItem,
  breadcrumb,
  buildTree,
  hasRole,
} from './tree';

const MODEL_KEY = 'on.chatModel.';
const POLL_MS = 4000;

@Component({
  selector: 'app-workbench',
  imports: [
    NgTemplateOutlet,
    FormsModule,
    RouterLink,
    MatTreeModule,
    MatButtonModule,
    MatButtonToggleModule,
    MatIconModule,
    MatMenuModule,
    MatSlideToggleModule,
    MatSelectModule,
    MatFormFieldModule,
    MatInputModule,
    MatTooltipModule,
    MatDividerModule,
    SearchPanelComponent,
    ChatPanelComponent,
    SourceViewerComponent,
    SourceDetailComponent,
    NotesPanelComponent,
  ],
  templateUrl: './workbench.component.html',
  styleUrl: './workbench.component.scss',
})
export class WorkbenchComponent {
  private readonly api = inject(ApiService);
  private readonly sourcesApi = inject(SourcesApi);
  private readonly dialog = inject(MatDialog);
  private readonly snack = inject(MatSnackBar);

  readonly nodes = signal<TreeNodeDto[]>([]);
  readonly sources = signal<SourceDto[]>([]);
  readonly tree = computed(() => buildTree(this.nodes(), this.sources()));
  readonly selectedId = signal<string | null>(null);
  readonly selected = computed(() => this.nodes().find((n) => n.id === this.selectedId()) ?? null);
  readonly path = computed(() => breadcrumb(this.nodes(), this.selectedId()));
  readonly projectId = computed(() => this.selected()?.project_id ?? null);
  readonly notebookId = computed(() =>
    this.selected()?.kind === 'notebook' ? this.selected()!.id : null,
  );
  readonly selectedSourceId = signal<string | null>(null);
  readonly selectedSource = computed(
    () => this.sources().find((s) => s.id === this.selectedSourceId()) ?? null,
  );
  readonly notesRefresh = signal(0);
  readonly mode = signal<'chat' | 'search'>('chat');
  readonly askRequest = signal<{ text: string; nonce: number } | null>(null);
  /** Cited passage open in the source viewer. */
  readonly viewing = signal<Citation | null>(null);
  /** Notebooks inside the scope where the user can save chat answers as notes. */
  readonly noteTargets = computed<NotebookOption[]>(() => {
    const scope = this.selectedId();
    if (!scope) return [];
    const nodes = this.nodes();
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const inScope = (n: TreeNodeDto): boolean => {
      for (let cur: TreeNodeDto | undefined = n; cur; cur = byId.get(cur.parent_id ?? '')) {
        if (cur.id === scope) return true;
      }
      return false;
    };
    return nodes
      .filter((n) => n.kind === 'notebook' && hasRole(n, 'editor') && inScope(n))
      .map((n) => ({ id: n.id, name: n.name }));
  });

  readonly chatModels = signal<ProviderModel[]>([]);
  readonly chatModelId = signal<string | null>(null);
  readonly modelError = signal<string | null>(null);
  readonly leftOpen = signal(true);
  readonly rightOpen = signal(true);

  protected readonly icons: Record<string, string> = KIND_ICONS;
  protected readonly sourceIcons = SOURCE_ICONS;
  protected readonly childKinds: Record<string, NodeKind[]> = CHILD_KINDS;
  protected readonly hasRole = hasRole;
  protected readonly isTerminal = (s: SourceDto) => TERMINAL.includes(s.status);
  childrenAccessor = (item: TreeItem) => item.children;
  hasChild = (_: number, item: TreeItem) => item.children.length > 0;
  trackBy = (_: number, item: TreeItem) => item.key;
  expansionKey = (item: TreeItem) => item.key;

  constructor() {
    void this.reload();
    effect(() => void this.loadChatModels(this.projectId()));
    // Poll while some source is still being processed.
    const timer = setInterval(() => {
      if (this.sources().some((s) => !TERMINAL.includes(s.status))) void this.reloadSources(true);
    }, POLL_MS);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  async reload(): Promise<void> {
    try {
      this.nodes.set(await this.api.nodes());
      await this.reloadSources(false);
    } catch (err) {
      this.toast(errorMessage(err));
    }
  }

  async reloadSources(fromPoll: boolean): Promise<void> {
    const before = this.sources();
    const after = await this.sourcesApi.list();
    this.sources.set(after);
    const noteChanged = after.some(
      (s) => s.kind === 'note' && before.find((b) => b.id === s.id)?.status !== s.status,
    );
    if (!fromPoll || noteChanged) this.notesRefresh.update((n) => n + 1);
  }

  private async loadChatModels(projectId: string | null): Promise<void> {
    this.modelError.set(null);
    try {
      const models = await this.api.selectableModels('chat', projectId);
      this.chatModels.set(models);
      const saved = localStorage.getItem(MODEL_KEY + (projectId ?? 'global'));
      this.chatModelId.set(models.find((m) => m.id === saved)?.id ?? models[0]?.id ?? null);
    } catch (err) {
      this.chatModels.set([]);
      this.modelError.set(errorMessage(err));
    }
  }

  selectModel(id: string): void {
    this.chatModelId.set(id);
    localStorage.setItem(MODEL_KEY + (this.projectId() ?? 'global'), id);
  }

  select(node: TreeNodeDto): void {
    // Ancestors shown for navigation only (role null) are still valid search scopes:
    // results are limited to the subtrees the user can read.
    this.selectedId.set(node.id);
    this.selectedSourceId.set(null);
    this.viewing.set(null);
  }

  /** Members of an archive show their file name; the full path is in the tooltip. */
  shortTitle(src: SourceDto): string {
    return src.parent_source_id && src.kind !== 'web' ? src.title.split('/').pop()! : src.title;
  }

  /** A suggested question of a source: chat about it in the source's notebook. */
  askAbout(src: SourceDto, question: string): void {
    this.selectedSourceId.set(null);
    this.viewing.set(null);
    this.selectedId.set(src.notebook_id);
    this.mode.set('chat');
    this.askRequest.set({ text: question, nonce: Date.now() });
  }

  openCitation(c: Citation): void {
    this.selectedSourceId.set(null);
    this.viewing.set({ ...c });
  }

  /** `keepScope` opens the details without changing the chat scope (e.g. from a citation). */
  openSource(id: string, keepScope = false): void {
    const src = this.sources().find((s) => s.id === id);
    if (src) {
      this.viewing.set(null);
      if (!keepScope) this.selectedId.set(src.notebook_id);
      this.selectedSourceId.set(id);
    }
  }

  async createProject(): Promise<void> {
    const name = await this.askName('New project', 'Project name');
    if (name) await this.run(() => this.api.createNode('project', name, null), 'Project created');
  }

  async createChild(parent: TreeNodeDto, kind: NodeKind): Promise<void> {
    const name = await this.askName(
      `New ${kind} in “${parent.name}”`,
      `${kind[0].toUpperCase()}${kind.slice(1)} name`,
    );
    if (name) await this.run(() => this.api.createNode(kind, name, parent.id), `${kind} created`);
  }

  async rename(node: TreeNodeDto): Promise<void> {
    const name = await this.askName(`Rename ${node.kind}`, 'Name', node.name);
    if (name && name !== node.name)
      await this.run(() => this.api.updateNode(node.id, { name }), 'Renamed');
  }

  async toggleActive(node: TreeNodeDto, active: boolean): Promise<void> {
    await this.run(
      () => this.api.updateNode(node.id, { active }),
      active ? 'Enabled for search' : 'Excluded from search (including everything inside)',
    );
  }

  async toggleSource(source: SourceDto, active: boolean): Promise<void> {
    await this.run(
      () => this.sourcesApi.update(source.id, { active }),
      active ? 'Source included in search' : 'Source excluded from search',
    );
  }

  async remove(node: TreeNodeDto): Promise<void> {
    if (!confirm(`Delete “${node.name}” and everything inside it, including its sources?`)) return;
    await this.run(() => this.api.deleteNode(node.id), 'Deleted');
    if (this.selectedId() === node.id) this.selectedId.set(null);
  }

  share(node: TreeNodeDto): void {
    this.dialog.open(ShareDialogComponent, { data: node, width: 'min(640px, 95vw)' });
  }

  private askName(title: string, label: string, value = ''): Promise<string | undefined> {
    const ref = this.dialog.open(NameDialogComponent, { data: { title, label, value } });
    return new Promise((resolve) =>
      ref.afterClosed().subscribe((v) => resolve(v as string | undefined)),
    );
  }

  private async run(action: () => Promise<unknown>, ok: string): Promise<void> {
    try {
      await action();
      this.toast(ok);
    } catch (err) {
      this.toast(errorMessage(err));
    }
    await this.reload();
  }

  private toast(message: string): void {
    this.snack.open(message, 'Close', { duration: 4000 });
  }
}
