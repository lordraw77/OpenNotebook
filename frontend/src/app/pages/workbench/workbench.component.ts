import { NgTemplateOutlet } from '@angular/common';
import { Component, DestroyRef, computed, effect, inject, input, signal } from '@angular/core';
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
import {
  Citation,
  SourceCounts,
  SourceDto,
  SourcesApi,
  TERMINAL,
  statusLabel,
} from '../../core/sources.api';
import { ChatPanelComponent, NotebookOption } from './chat-panel.component';
import { NameDialogComponent, ShareDialogComponent } from './dialogs';
import { ProjectSettingsDialogComponent } from './project-settings.dialog';
import { NotesPanelComponent } from './notes-panel.component';
import { SearchPanelComponent } from './search-panel.component';
import { SourceDetailComponent } from './source-detail.component';
import { SourceViewerComponent } from './source-viewer.component';
import {
  CHILD_KINDS,
  KIND_ICONS,
  SourcePage,
  TreeItem,
  breadcrumb,
  buildTree,
  hasRole,
  kindLabel,
  newKindLabel,
  sourceIcon,
  sourceKey,
} from './tree';
import { TranslatePipe, t } from '../../core/i18n';

const MODEL_KEY = 'on.chatModel.';
const POLL_MS = 4000;
/** Sources loaded per expanded node or archive; "Load more" fetches the next page. */
export const PAGE_SIZE = 100;

@Component({
  selector: 'app-workbench',
  imports: [
    TranslatePipe,
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
  protected readonly statusLabel = statusLabel;
  private readonly api = inject(ApiService);
  private readonly sourcesApi = inject(SourcesApi);
  private readonly dialog = inject(MatDialog);
  private readonly snack = inject(MatSnackBar);

  /** Deep link /workbench?source=<id> (e.g. from a wiki citation) opens that source. */
  readonly source = input<string | undefined>();

  readonly nodes = signal<TreeNodeDto[]>([]);
  /** Loaded pages of sources, by tree key (node id, or `s:<id>` for the members of an archive or crawl). */
  readonly pages = signal<ReadonlyMap<string, SourcePage>>(new Map());
  readonly counts = signal<SourceCounts>({ nodes: {}, processing: 0 });
  readonly tree = computed(() => buildTree(this.nodes(), this.pages(), this.counts().nodes));
  /** Keys of the expanded tree items, so lists that gain their first sources while open get loaded. */
  private readonly expanded = new Set<string>();
  /** Source opened from outside the loaded pages (deep link, citation). */
  private readonly openedSource = signal<SourceDto | null>(null);
  readonly selectedId = signal<string | null>(null);
  readonly selected = computed(() => this.nodes().find((n) => n.id === this.selectedId()) ?? null);
  readonly path = computed(() => breadcrumb(this.nodes(), this.selectedId()));
  readonly projectId = computed(() => this.selected()?.project_id ?? null);
  readonly notebookId = computed(() =>
    this.selected()?.kind === 'notebook' ? this.selected()!.id : null,
  );
  readonly selectedSourceId = signal<string | null>(null);
  readonly selectedSource = computed(() => {
    const id = this.selectedSourceId();
    if (!id) return null;
    return this.loadedSource(id) ?? (this.openedSource()?.id === id ? this.openedSource() : null);
  });
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
  protected readonly sourceIcon = sourceIcon;
  protected readonly childKinds: Record<string, NodeKind[]> = CHILD_KINDS;
  protected readonly hasRole = hasRole;
  protected readonly newKindLabel = newKindLabel;
  protected readonly kindLabel = kindLabel;
  protected readonly isTerminal = (s: SourceDto) => TERMINAL.includes(s.status);
  childrenAccessor = (item: TreeItem) => item.children;
  hasChild = (_: number, item: TreeItem) => item.children.length > 0;
  isPlaceholder = (_: number, item: TreeItem) => !!item.placeholder;
  trackBy = (_: number, item: TreeItem) => item.key;
  expansionKey = (item: TreeItem) => item.key;

  constructor() {
    void this.reload();
    effect(() => void this.loadChatModels(this.projectId()));
    // Poll while some source is still being processed.
    const timer = setInterval(() => {
      if (this.counts().processing > 0) void this.reloadSources(true);
    }, POLL_MS);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  async reload(): Promise<void> {
    try {
      this.nodes.set(await this.api.nodes());
      await this.reloadSources(false);
      const wanted = this.source();
      if (wanted && !this.selectedSourceId()) await this.openSource(wanted);
    } catch (err) {
      this.toast(errorMessage(err));
    }
  }

  /** Refreshes the counts and every loaded page (keeping how much of each list is shown). */
  async reloadSources(fromPoll: boolean): Promise<void> {
    const before = this.counts().processing;
    const [counts, pages] = await Promise.all([
      this.sourcesApi.counts(),
      Promise.all(
        [...this.pages()].map(async ([key, page]) => {
          const limit = Math.max(PAGE_SIZE, Math.ceil(page.items.length / PAGE_SIZE) * PAGE_SIZE);
          return [key, await this.fetchPage(key, 0, limit)] as const;
        }),
      ),
    ]);
    this.counts.set(counts);
    // drop lists whose owner is gone (deleted node or source)
    this.pages.set(new Map(pages.filter(([, page]) => page !== null) as [string, SourcePage][]));
    const opened = this.openedSource();
    if (opened && !this.loadedSource(opened.id) && !TERMINAL.includes(opened.status)) {
      this.openedSource.set(await this.sourcesApi.get(opened.id).catch(() => null));
    }
    this.loadExpandedLists(this.tree());
    if (!fromPoll || counts.processing !== before) this.notesRefresh.update((n) => n + 1);
  }

  /** Expanding a node or an archive loads its first page of sources. */
  onExpand(item: TreeItem, expanded: boolean): void {
    if (expanded) this.expanded.add(item.key);
    else this.expanded.delete(item.key);
    if (expanded && this.waitingForPage(item)) void this.loadPage(item.key, 0);
  }

  private waitingForPage(item: TreeItem): boolean {
    return !this.pages().has(item.key) && item.children.some((c) => c.placeholder === 'loading');
  }

  /** Loads the lists of expanded items that show the loading row (e.g. a first upload into an open node). */
  private loadExpandedLists(items: TreeItem[]): void {
    for (const item of items) {
      if (this.expanded.has(item.key)) {
        if (this.waitingForPage(item)) void this.loadPage(item.key, 0);
        this.loadExpandedLists(item.children);
      }
    }
  }

  loadMore(item: TreeItem): void {
    const owner = item.owner!;
    void this.loadPage(owner, this.pages().get(owner)?.items.length ?? 0);
  }

  private async loadPage(key: string, offset: number): Promise<void> {
    try {
      const page = await this.fetchPage(key, offset, PAGE_SIZE);
      if (!page) return;
      this.pages.update((pages) => {
        const next = new Map(pages);
        const items =
          offset > 0
            ? [...(pages.get(key)?.items ?? []).slice(0, offset), ...page.items]
            : page.items;
        next.set(key, { items, total: page.total });
        return next;
      });
    } catch (err) {
      this.toast(errorMessage(err));
    }
  }

  /** `null` when the owner of the list no longer exists or is no longer readable. */
  private async fetchPage(key: string, offset: number, limit: number): Promise<SourcePage | null> {
    if (key.startsWith('s:')) {
      const parentId = key.slice(2);
      if (!this.loadedSource(parentId)) return null;
      return this.sourcesApi.page({ parentId, offset, limit });
    }
    if (!this.nodes().some((n) => n.id === key)) return null;
    return this.sourcesApi.page({ nodeId: key, topLevel: true, offset, limit });
  }

  private loadedSource(id: string): SourceDto | null {
    for (const page of this.pages().values()) {
      const found = page.items.find((s) => s.id === id);
      if (found) return found;
    }
    return null;
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
  async openSource(id: string, keepScope = false): Promise<void> {
    let src = this.loadedSource(id);
    if (!src) {
      try {
        src = await this.sourcesApi.get(id);
      } catch (err) {
        this.toast(errorMessage(err));
        return;
      }
      this.openedSource.set(src);
    }
    this.viewing.set(null);
    if (!keepScope) this.selectedId.set(src.notebook_id);
    this.selectedSourceId.set(id);
  }

  async createProject(): Promise<void> {
    const name = await this.askName(t('New project'), t('Project name'));
    if (name)
      await this.run(() => this.api.createNode('project', name, null), t('Project created'));
  }

  async createChild(parent: TreeNodeDto, kind: NodeKind): Promise<void> {
    const name = await this.askName(
      t('{what} in “{parent}”', { what: newKindLabel(kind), parent: parent.name }),
      t('Name'),
    );
    if (name)
      await this.run(
        () => this.api.createNode(kind, name, parent.id),
        t('Created: {name}', { name }),
      );
  }

  async rename(node: TreeNodeDto): Promise<void> {
    const name = await this.askName(
      t('Rename {kind}', { kind: kindLabel(node.kind) }),
      t('Name'),
      node.name,
    );
    if (name && name !== node.name)
      await this.run(() => this.api.updateNode(node.id, { name }), t('Renamed'));
  }

  async toggleActive(node: TreeNodeDto, active: boolean): Promise<void> {
    await this.run(
      () => this.api.updateNode(node.id, { active }),
      active ? t('Enabled for search') : t('Excluded from search (including everything inside)'),
    );
  }

  async toggleSource(source: SourceDto, active: boolean): Promise<void> {
    await this.run(
      () => this.sourcesApi.update(source.id, { active }),
      active ? t('Source included in search') : t('Source excluded from search'),
    );
  }

  async remove(node: TreeNodeDto): Promise<void> {
    if (
      !confirm(
        t('Delete “{name}” and everything inside it, including its sources?', { name: node.name }),
      )
    )
      return;
    await this.run(() => this.api.deleteNode(node.id), t('Deleted'));
    if (this.selectedId() === node.id) this.selectedId.set(null);
  }

  projectSettings(node: TreeNodeDto): void {
    this.dialog.open(ProjectSettingsDialogComponent, { data: node, width: 'min(640px, 95vw)' });
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
    this.snack.open(message, t('Close'), { duration: 4000 });
  }
}
