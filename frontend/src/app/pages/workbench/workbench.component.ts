import { NgTemplateOutlet } from '@angular/common';
import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
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

import { NodeKind, ProviderModel, TreeNodeDto } from '../../core/api.models';
import { ApiService, errorMessage } from '../../core/api.service';
import { NameDialogComponent, ShareDialogComponent } from './dialogs';
import { CHILD_KINDS, KIND_ICONS, TreeItem, breadcrumb, buildTree, hasRole } from './tree';

const MODEL_KEY = 'on.chatModel.';

@Component({
  selector: 'app-workbench',
  imports: [
    NgTemplateOutlet,
    FormsModule,
    MatTreeModule,
    MatButtonModule,
    MatIconModule,
    MatMenuModule,
    MatSlideToggleModule,
    MatSelectModule,
    MatFormFieldModule,
    MatInputModule,
    MatTooltipModule,
    MatDividerModule,
  ],
  templateUrl: './workbench.component.html',
  styleUrl: './workbench.component.scss',
})
export class WorkbenchComponent {
  private readonly api = inject(ApiService);
  private readonly dialog = inject(MatDialog);
  private readonly snack = inject(MatSnackBar);

  readonly nodes = signal<TreeNodeDto[]>([]);
  readonly tree = computed(() => buildTree(this.nodes()));
  readonly selectedId = signal<string | null>(null);
  readonly selected = computed(() => this.nodes().find((n) => n.id === this.selectedId()) ?? null);
  readonly path = computed(() => breadcrumb(this.nodes(), this.selectedId()));
  readonly projectId = computed(() => this.selected()?.project_id ?? null);

  readonly chatModels = signal<ProviderModel[]>([]);
  readonly chatModelId = signal<string | null>(null);
  readonly modelError = signal<string | null>(null);
  readonly leftOpen = signal(true);
  readonly rightOpen = signal(true);
  question = '';

  protected readonly icons: Record<string, string> = KIND_ICONS;
  protected readonly childKinds: Record<string, NodeKind[]> = CHILD_KINDS;
  protected readonly hasRole = hasRole;
  childrenAccessor = (item: TreeItem) => item.children;
  hasChild = (_: number, item: TreeItem) => item.children.length > 0;
  trackBy = (_: number, item: TreeItem) => item.node.id;
  expansionKey = (item: TreeItem) => item.node.id;

  constructor() {
    void this.reload();
    // Reload the selectable chat models whenever the project in scope changes.
    effect(() => void this.loadChatModels(this.projectId()));
  }

  async reload(): Promise<void> {
    try {
      this.nodes.set(await this.api.nodes());
    } catch (err) {
      this.toast(errorMessage(err));
    }
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
    if (node.role !== null) this.selectedId.set(node.id);
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

  async remove(node: TreeNodeDto): Promise<void> {
    if (!confirm(`Delete “${node.name}” and everything inside it?`)) return;
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
