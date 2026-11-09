import { DatePipe } from '@angular/common';
import { Component, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router } from '@angular/router';

import { TreeNodeDto } from '../../core/api.models';
import { ApiService, errorMessage } from '../../core/api.service';
import {
  ENTITY_ICONS,
  ENTITY_TYPES,
  EntityDetail,
  EntityDto,
  GraphApi,
  WikiPageDto,
} from '../../core/graph.api';
import { Citation, citationLocation } from '../../core/sources.api';
import { AnswerViewComponent } from '../workbench/answer-view.component';
import { SourceViewerComponent } from '../workbench/source-viewer.component';
import { breadcrumb } from '../workbench/tree';
import { LaidEdge, bounds, layoutGraph } from './graph-layout';
import { TranslatePipe, t } from '../../core/i18n';

const TYPE_COLORS: Record<string, string> = {
  person: '#e879f9',
  organization: '#f472b6',
  product: '#a78bfa',
  component: '#818cf8',
  technology: '#60a5fa',
  concept: '#22d3ee',
  location: '#34d399',
  event: '#fbbf24',
  document: '#94a3b8',
  standard: '#2dd4bf',
  file: '#94a3b8',
  function: '#38bdf8',
  class: '#c084fc',
  struct: '#c084fc',
  interface: '#f0abfc',
  module: '#fb923c',
};

/** Knowledge graph and wiki pages of a scope, built only from the sources the user can see. */
@Component({
  selector: 'app-wiki',
  imports: [
    TranslatePipe,
    DatePipe,
    FormsModule,
    MatButtonModule,
    MatButtonToggleModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressBarModule,
    MatSelectModule,
    MatTooltipModule,
    AnswerViewComponent,
    SourceViewerComponent,
  ],
  template: `
    <div class="wiki">
      <aside class="side">
        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>{{ 'Scope' | t }}</mat-label>
          <mat-select [value]="scopeId()" (valueChange)="setScope($event)">
            @for (n of scopes(); track n.id) {
              <mat-option [value]="n.id">{{ label(n) }}</mat-option>
            }
          </mat-select>
        </mat-form-field>
        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>{{ 'Find an entity' | t }}</mat-label>
          <mat-icon matPrefix>search</mat-icon>
          <input matInput [ngModel]="query()" (ngModelChange)="query.set($event)" />
        </mat-form-field>
        <div class="types">
          @for (t of availableTypes(); track t) {
            <button
              type="button"
              class="type"
              [class.on]="typeFilter() === t"
              (click)="typeFilter.set(typeFilter() === t ? null : t)"
            >
              <span class="dot" [style.background]="color(t)"></span>{{ t }}
            </button>
          }
        </div>
        @if (loadingList()) {
          <mat-progress-bar mode="indeterminate"></mat-progress-bar>
        }
        <nav class="list" [attr.aria-label]="'Entities' | t">
          @for (e of filtered(); track e.id) {
            <button
              type="button"
              class="entity"
              [class.selected]="e.id === entityId()"
              (click)="openEntity(e.id)"
            >
              <mat-icon [style.color]="color(e.type)">{{ icon(e.type) }}</mat-icon>
              <span class="name">{{ e.name }}</span>
              <span class="count" [matTooltip]="'Mentions' | t">{{ e.mentions }}</span>
            </button>
          } @empty {
            @if (!loadingList()) {
              <p class="muted pad">
                {{
                  'No entities yet. They are extracted after indexing when a graph extraction model is configured (Settings → Models); source code needs no model.'
                    | t
                }}
              </p>
            }
          }
        </nav>
      </aside>

      <section class="main">
        <header class="bar">
          <mat-button-toggle-group
            hideSingleSelectionIndicator
            [value]="view()"
            (change)="view.set($event.value)"
            [attr.aria-label]="'View' | t"
          >
            <mat-button-toggle value="graph"
              ><mat-icon>hub</mat-icon> {{ 'Graph' | t }}</mat-button-toggle
            >
            <mat-button-toggle value="page" [disabled]="!entityId()"
              ><mat-icon>article</mat-icon> {{ 'Page' | t }}</mat-button-toggle
            >
          </mat-button-toggle-group>
          <span class="muted">{{ '{n} entities in scope' | t: { n: entities().length } }}</span>
        </header>

        @if (viewing(); as c) {
          <app-source-viewer
            [citation]="c"
            (closed)="viewing.set(null)"
            (details)="openInWorkbench(c)"
          />
        } @else if (view() === 'graph') {
          <div class="graph-wrap">
            @if (laid().nodes.length === 0) {
              <p class="muted pad">{{ 'Nothing to show in this scope yet.' | t }}</p>
            }
            <svg
              class="graph"
              [attr.viewBox]="viewBox().join(' ')"
              (wheel)="zoom($event)"
              (pointerdown)="panStart($event)"
              (pointermove)="panMove($event)"
              (pointerup)="panEnd()"
              (pointerleave)="panEnd()"
              role="img"
              [attr.aria-label]="'Knowledge graph' | t"
            >
              @for (e of laid().edges; track $index) {
                <line
                  class="edge"
                  [attr.x1]="e.source.x"
                  [attr.y1]="e.source.y"
                  [attr.x2]="e.target.x"
                  [attr.y2]="e.target.y"
                  [class.hot]="isHot(e)"
                >
                  <title>{{ e.source.name }} {{ e.type }} {{ e.target.name }}</title>
                </line>
              }
              @for (n of laid().nodes; track n.id) {
                <g
                  class="node"
                  [attr.transform]="'translate(' + n.x + ',' + n.y + ')'"
                  (click)="openEntity(n.id)"
                  (pointerenter)="hover.set(n.id)"
                  (pointerleave)="hover.set(null)"
                  [class.selected]="n.id === entityId()"
                >
                  <circle [attr.r]="n.r" [attr.fill]="color(n.type)"></circle>
                  @if (n.r > 9 || hover() === n.id || n.id === entityId()) {
                    <text [attr.y]="n.r + 13">{{ n.name }}</text>
                  }
                  <title>
                    {{
                      '{name} ({type}, {n} mentions)'
                        | t: { name: n.name, type: n.type, n: n.mentions }
                    }}
                  </title>
                </g>
              }
            </svg>
          </div>
        } @else if (detail(); as d) {
          <article class="page">
            <header class="title">
              <mat-icon [style.color]="color(d.type)">{{ icon(d.type) }}</mat-icon>
              <div>
                <h1>{{ d.name }}</h1>
                <div class="muted">
                  {{ d.type }} · {{ d.mention_count }}
                  {{ d.mention_count === 1 ? ('mention' | t) : ('mentions' | t) }}
                  @if (d.aliases.length) {
                    · {{ 'also: {names}' | t: { names: d.aliases.join(', ') } }}
                  }
                </div>
              </div>
              <span class="spacer"></span>
              <button
                mat-icon-button
                [matTooltip]="'Edit the graph' | t"
                [attr.aria-label]="'Edit the graph' | t"
                [class.on]="editing()"
                (click)="toggleEdit(d)"
              >
                <mat-icon>edit</mat-icon>
              </button>
              <button
                mat-icon-button
                [matTooltip]="'Rewrite the page' | t"
                [attr.aria-label]="'Rewrite the page' | t"
                [disabled]="writing()"
                (click)="loadWiki(d.id, true)"
              >
                <mat-icon>refresh</mat-icon>
              </button>
            </header>

            @if (editing()) {
              <section class="edit">
                <p class="muted small">
                  {{
                    'Edits apply to the whole project and are kept when sources are indexed again. They need the editor role on the project.'
                      | t
                  }}
                </p>
                @if (editError()) {
                  <p class="error-text">{{ editError() }}</p>
                }
                <div class="edit-row">
                  <mat-form-field appearance="outline" subscriptSizing="dynamic">
                    <mat-label>{{ 'Name' | t }}</mat-label>
                    <input matInput [(ngModel)]="editName" />
                  </mat-form-field>
                  <mat-form-field appearance="outline" subscriptSizing="dynamic">
                    <mat-label>{{ 'Type' | t }}</mat-label>
                    <mat-select [(ngModel)]="editType">
                      @for (k of entityTypes; track k) {
                        <mat-option [value]="k">{{ k }}</mat-option>
                      }
                    </mat-select>
                  </mat-form-field>
                  <button mat-stroked-button (click)="saveEntity(d)">{{ 'Save' | t }}</button>
                </div>
                <div class="edit-row">
                  <mat-form-field appearance="outline" subscriptSizing="dynamic" class="grow">
                    <mat-label>{{ 'Merge into' | t }}</mat-label>
                    <mat-select [(ngModel)]="mergeTarget">
                      @for (e of otherEntities(); track e.id) {
                        <mat-option [value]="e.id">{{ e.name }} ({{ e.type }})</mat-option>
                      }
                    </mat-select>
                  </mat-form-field>
                  <button mat-stroked-button [disabled]="!mergeTarget" (click)="merge(d)">
                    {{ 'Merge' | t }}
                  </button>
                  <button mat-stroked-button color="warn" (click)="removeEntity(d)">
                    {{ 'Delete entity' | t }}
                  </button>
                </div>
                <div class="edit-row">
                  <mat-form-field appearance="outline" subscriptSizing="dynamic">
                    <mat-label>{{ 'Relation' | t }}</mat-label>
                    <input matInput [(ngModel)]="relType" placeholder="depends_on" />
                  </mat-form-field>
                  <mat-form-field appearance="outline" subscriptSizing="dynamic" class="grow">
                    <mat-label>{{ 'To' | t }}</mat-label>
                    <mat-select [(ngModel)]="relTarget">
                      @for (e of otherEntities(); track e.id) {
                        <mat-option [value]="e.id">{{ e.name }} ({{ e.type }})</mat-option>
                      }
                    </mat-select>
                  </mat-form-field>
                  <button
                    mat-stroked-button
                    [disabled]="!relType.trim() || !relTarget"
                    (click)="addRelation(d)"
                  >
                    {{ 'Add relation' | t }}
                  </button>
                </div>
              </section>
            }

            <section class="body">
              @if (writing()) {
                <div class="muted">
                  <mat-progress-bar mode="indeterminate"></mat-progress-bar>
                  {{ 'Writing the page from the passages you can read…' | t }}
                </div>
              } @else if (wikiError()) {
                <p class="error-text">{{ wikiError() }}</p>
                @for (text of d.descriptions; track text) {
                  <p>{{ text }}</p>
                }
              } @else if (wiki(); as w) {
                <app-answer-view
                  [content]="w.body_md"
                  [citations]="w.citations"
                  (cite)="viewing.set($event)"
                />
                <p class="muted small">
                  {{ 'Written by {model}' | t: { model: w.model_label } }}
                  @if (w.generated_at) {
                    · {{ w.generated_at | date: 'short' }}
                  }
                  {{ '· only from sources you can read' | t }}
                </p>
              }
            </section>

            @if (d.related.length) {
              <h2>{{ 'Related' | t }}</h2>
              <div class="related">
                @for (r of d.related; track r.entity_id + r.relation + r.direction) {
                  <button
                    type="button"
                    class="rel"
                    (click)="openEntity(r.entity_id)"
                    [matTooltip]="r.description ?? ''"
                  >
                    <span class="verb">{{
                      r.direction === 'out' ? r.relation + ' →' : '← ' + r.relation
                    }}</span>
                    <mat-icon [style.color]="color(r.type)">{{ icon(r.type) }}</mat-icon>
                    {{ r.name }}
                  </button>
                  @if (editing()) {
                    <button
                      mat-icon-button
                      class="rel-del"
                      [matTooltip]="'Delete this relation' | t"
                      [attr.aria-label]="'Delete this relation' | t"
                      (click)="removeRelation(r.relation_id)"
                    >
                      <mat-icon>close</mat-icon>
                    </button>
                  }
                }
              </div>
            }

            <h2>{{ 'Mentioned in' | t }}</h2>
            <div class="mentions">
              @for (m of d.mentions; track m.chunk_id) {
                <button type="button" class="mention" (click)="viewing.set(m)">
                  <div class="where">
                    <strong>{{ m.source_title }}</strong>
                    <span class="muted"
                      >{{ m.notebook_name }}{{ loc(m) ? ' · ' + loc(m) : '' }}</span
                    >
                  </div>
                  @if (m.description) {
                    <div>{{ m.description }}</div>
                  }
                  <div class="excerpt muted">{{ (m.text ?? '').slice(0, 220) }}…</div>
                </button>
              }
            </div>
          </article>
        } @else if (entityError()) {
          <p class="error-text pad">{{ entityError() }}</p>
        }
      </section>
    </div>
  `,
  styles: `
    :host {
      display: block;
      height: 100%;
    }
    .wiki {
      display: grid;
      grid-template-columns: 320px 1fr;
      height: 100%;
      min-height: 0;
    }
    .side {
      display: flex;
      flex-direction: column;
      gap: 10px;
      padding: 12px;
      border-right: 1px solid var(--mat-sys-outline-variant);
      min-height: 0;
    }
    .types {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
    }
    .type {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 2px 9px;
      border-radius: 12px;
      border: 1px solid var(--mat-sys-outline-variant);
      background: transparent;
      color: var(--mat-sys-on-surface);
      font: var(--mat-sys-label-small);
      cursor: pointer;
    }
    .type.on {
      background: var(--mat-sys-primary-container);
      color: var(--mat-sys-on-primary-container);
      border-color: transparent;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
    }
    .list {
      flex: 1;
      overflow: auto;
      min-height: 0;
    }
    .entity {
      display: flex;
      align-items: center;
      gap: 8px;
      width: 100%;
      padding: 6px 8px;
      border: 0;
      border-radius: 10px;
      background: transparent;
      color: var(--mat-sys-on-surface);
      font: var(--mat-sys-body-medium);
      text-align: left;
      cursor: pointer;
    }
    .entity:hover {
      background: var(--mat-sys-surface-container-high);
    }
    .entity.selected {
      background: var(--mat-sys-secondary-container);
      color: var(--mat-sys-on-secondary-container);
    }
    .entity mat-icon {
      font-size: 20px;
      width: 20px;
      height: 20px;
      flex: none;
    }
    .entity .name {
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .count {
      font-size: 11px;
      padding: 0 7px;
      border-radius: 9px;
      background: var(--mat-sys-surface-container-highest);
    }
    .main {
      display: flex;
      flex-direction: column;
      min-height: 0;
      min-width: 0;
    }
    .bar {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 10px 16px;
    }
    .bar mat-icon {
      font-size: 18px;
      width: 18px;
      height: 18px;
      vertical-align: -4px;
    }
    .graph-wrap {
      flex: 1;
      min-height: 0;
      position: relative;
    }
    .graph {
      width: 100%;
      height: 100%;
      cursor: grab;
      touch-action: none;
    }
    .edge {
      stroke: var(--mat-sys-outline-variant);
      stroke-width: 1.2;
    }
    .edge.hot {
      stroke: var(--mat-sys-primary);
      stroke-width: 2;
    }
    .node {
      cursor: pointer;
    }
    .node circle {
      stroke: var(--mat-sys-surface);
      stroke-width: 2;
    }
    .node.selected circle {
      stroke: var(--mat-sys-primary);
      stroke-width: 4;
    }
    .node text {
      font: 11px var(--mat-sys-body-small-font, sans-serif);
      fill: var(--mat-sys-on-surface);
      text-anchor: middle;
      paint-order: stroke;
      stroke: var(--mat-sys-surface);
      stroke-width: 3px;
    }
    .page {
      overflow: auto;
      padding: 8px 24px 32px;
      max-width: 900px;
    }
    .title {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .title mat-icon {
      font-size: 36px;
      width: 36px;
      height: 36px;
    }
    h1 {
      font: var(--mat-sys-headline-small);
      margin: 0;
    }
    h2 {
      font: var(--mat-sys-title-medium);
      margin: 24px 0 8px;
    }
    .spacer {
      flex: 1;
    }
    .body {
      margin-top: 16px;
      padding: 16px 20px;
      border-radius: 14px;
      background: var(--mat-sys-surface-container);
      border: 1px solid var(--mat-sys-outline-variant);
    }
    .small {
      font-size: 12px;
      margin: 8px 0 0;
    }
    .related {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .rel {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 12px 4px 8px;
      border-radius: 16px;
      border: 1px solid var(--mat-sys-outline-variant);
      background: var(--mat-sys-surface-container-low);
      color: var(--mat-sys-on-surface);
      font: var(--mat-sys-label-large);
      cursor: pointer;
    }
    .rel:hover {
      border-color: var(--mat-sys-primary);
    }
    .rel mat-icon {
      font-size: 18px;
      width: 18px;
      height: 18px;
    }
    .verb {
      font: var(--mat-sys-label-small);
      color: var(--mat-sys-on-surface-variant);
    }
    .mentions {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .mention {
      text-align: left;
      padding: 10px 14px;
      border-radius: 12px;
      border: 1px solid var(--mat-sys-outline-variant);
      background: transparent;
      color: var(--mat-sys-on-surface);
      font: var(--mat-sys-body-medium);
      cursor: pointer;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .mention:hover {
      border-color: var(--mat-sys-primary);
    }
    .where {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: baseline;
    }
    .excerpt {
      font-size: 13px;
      white-space: pre-wrap;
    }
    .pad {
      padding: 0 16px;
    }
    .edit {
      display: flex;
      flex-direction: column;
      gap: 10px;
      padding: 12px;
      margin: 8px 0;
      border: 1px solid var(--mat-sys-outline-variant);
      border-radius: 8px;
    }
    .edit-row {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }
    .edit-row .grow {
      flex: 1;
      min-width: 180px;
    }
    .rel-del {
      transform: scale(0.7);
    }
    @media (max-width: 900px) {
      .wiki {
        grid-template-columns: 1fr;
        grid-template-rows: 40vh 1fr;
      }
      .side {
        border-right: 0;
        border-bottom: 1px solid var(--mat-sys-outline-variant);
      }
    }
  `,
})
export class WikiComponent {
  private readonly api = inject(ApiService);
  private readonly graphApi = inject(GraphApi);
  private readonly router = inject(Router);

  /** Deep links: /wiki?scope=<node>&entity=<id> */
  readonly scope = input<string | undefined>();
  readonly entity = input<string | undefined>();

  private readonly nodes = signal<TreeNodeDto[]>([]);
  readonly scopes = computed(() => this.nodes());
  readonly scopeId = signal<string | null>(null);
  readonly entities = signal<EntityDto[]>([]);
  readonly loadingList = signal(false);
  readonly query = signal('');
  readonly typeFilter = signal<string | null>(null);
  readonly availableTypes = computed(() => [...new Set(this.entities().map((e) => e.type))].sort());
  readonly filtered = computed(() => {
    const q = this.query().trim().toLowerCase();
    const t = this.typeFilter();
    return this.entities().filter(
      (e) => (!t || e.type === t) && (!q || e.name.toLowerCase().includes(q)),
    );
  });

  readonly view = signal<'graph' | 'page'>('graph');
  readonly entityId = signal<string | null>(null);
  readonly detail = signal<EntityDetail | null>(null);
  readonly entityError = signal<string | null>(null);
  readonly wiki = signal<WikiPageDto | null>(null);
  readonly writing = signal(false);
  readonly wikiError = signal<string | null>(null);
  readonly viewing = signal<Citation | null>(null);

  private readonly graphData = signal<{
    nodes: EntityDto[];
    edges: { source: string; target: string; type: string; weight: number }[];
  }>({ nodes: [], edges: [] });
  readonly laid = computed(() => layoutGraph(this.graphData().nodes, this.graphData().edges));
  readonly viewBox = signal<[number, number, number, number]>([-100, -100, 200, 200]);
  readonly hover = signal<string | null>(null);
  private pan: { x: number; y: number; box: [number, number, number, number] } | null = null;

  protected readonly loc = citationLocation;
  protected readonly entityTypes = ENTITY_TYPES;

  // graph editor
  readonly editing = signal(false);
  readonly editError = signal<string | null>(null);
  editName = '';
  editType = 'concept';
  mergeTarget: string | null = null;
  relType = '';
  relTarget: string | null = null;
  readonly otherEntities = computed(() => this.entities().filter((e) => e.id !== this.entityId()));

  constructor() {
    void this.api.nodes().then((nodes) => {
      this.nodes.set(nodes);
      const wanted = this.scope();
      const initial = nodes.find((n) => n.id === wanted) ?? nodes.find((n) => n.kind === 'project');
      if (initial) this.setScope(initial.id);
      const entity = this.entity();
      if (entity) void this.openEntity(entity);
    });
    effect(() => {
      const l = this.laid();
      untracked(() => this.viewBox.set(bounds(l.nodes)));
    });
  }

  label(n: TreeNodeDto): string {
    return breadcrumb(this.nodes(), n.id)
      .map((x) => x.name)
      .join(' / ');
  }

  setScope(id: string): void {
    this.scopeId.set(id);
    this.viewing.set(null);
    void this.loadScope(id);
    if (this.entityId()) void this.openEntity(this.entityId()!);
  }

  private async loadScope(id: string): Promise<void> {
    this.loadingList.set(true);
    try {
      const [entities, graph] = await Promise.all([
        this.graphApi.entities(id),
        this.graphApi.graph(id),
      ]);
      if (this.scopeId() !== id) return;
      this.entities.set(entities);
      this.graphData.set(graph);
    } catch (err) {
      this.entities.set([]);
      this.graphData.set({ nodes: [], edges: [] });
      this.entityError.set(errorMessage(err));
    } finally {
      this.loadingList.set(false);
    }
  }

  async openEntity(id: string): Promise<void> {
    const scope = this.scopeId();
    if (!scope) return;
    this.entityId.set(id);
    this.view.set('page');
    this.viewing.set(null);
    this.entityError.set(null);
    this.detail.set(null);
    try {
      this.detail.set(await this.graphApi.entity(id, scope));
      void this.router.navigate([], {
        queryParams: { scope, entity: id },
        replaceUrl: true,
      });
      await this.loadWiki(id, false);
    } catch (err) {
      this.entityError.set(errorMessage(err));
    }
  }

  async loadWiki(id: string, refresh: boolean): Promise<void> {
    const scope = this.scopeId();
    if (!scope) return;
    this.writing.set(true);
    this.wikiError.set(null);
    this.wiki.set(null);
    try {
      const page = await this.graphApi.wiki(id, scope, refresh);
      if (this.entityId() === id) this.wiki.set(page);
    } catch (err) {
      if (this.entityId() === id) this.wikiError.set(errorMessage(err));
    } finally {
      this.writing.set(false);
    }
  }

  openInWorkbench(c: Citation): void {
    void this.router.navigate(['/workbench'], { queryParams: { source: c.source_id } });
  }

  color(type: string): string {
    return TYPE_COLORS[type] ?? '#94a3b8';
  }

  icon(type: string): string {
    return ENTITY_ICONS[type] ?? 'label';
  }

  isHot(e: LaidEdge): boolean {
    const id = this.hover() ?? this.entityId();
    return e.source.id === id || e.target.id === id;
  }

  zoom(event: WheelEvent): void {
    event.preventDefault();
    const [x, y, w, h] = this.viewBox();
    const factor = event.deltaY > 0 ? 1.15 : 1 / 1.15;
    const nw = w * factor;
    const nh = h * factor;
    this.viewBox.set([x + (w - nw) / 2, y + (h - nh) / 2, nw, nh]);
  }

  panStart(event: PointerEvent): void {
    if ((event.target as Element).closest('.node')) return;
    this.pan = { x: event.clientX, y: event.clientY, box: this.viewBox() };
  }

  panMove(event: PointerEvent): void {
    if (!this.pan) return;
    const svg = event.currentTarget as SVGSVGElement;
    const [x, y, w, h] = this.pan.box;
    const scale = w / (svg.clientWidth || 1);
    this.viewBox.set([
      x - (event.clientX - this.pan.x) * scale,
      y - (event.clientY - this.pan.y) * scale,
      w,
      h,
    ]);
  }

  panEnd(): void {
    this.pan = null;
  }

  toggleEdit(d: EntityDetail): void {
    this.editing.set(!this.editing());
    this.editError.set(null);
    this.editName = d.name;
    this.editType = d.type;
    this.mergeTarget = null;
    this.relTarget = null;
    this.relType = '';
  }

  private async edited(work: () => Promise<unknown>, reopen: string | null): Promise<void> {
    this.editError.set(null);
    try {
      await work();
    } catch (err) {
      this.editError.set(errorMessage(err));
      return;
    }
    const scope = this.scopeId();
    if (scope) await this.loadScope(scope);
    if (reopen) await this.openEntity(reopen);
    else {
      this.entityId.set(null);
      this.detail.set(null);
      this.view.set('graph');
    }
    this.editing.set(reopen !== null && this.editing());
  }

  saveEntity(d: EntityDetail): Promise<void> {
    const scope = this.scopeId()!;
    return this.edited(
      () => this.graphApi.editEntity(d.id, scope, { name: this.editName, type: this.editType }),
      d.id,
    );
  }

  merge(d: EntityDetail): Promise<void> {
    const scope = this.scopeId()!;
    const target = this.mergeTarget!;
    return this.edited(() => this.graphApi.mergeEntity(d.id, scope, target), target);
  }

  removeEntity(d: EntityDetail): Promise<void> {
    if (
      !confirm(
        t('Delete "{name}" from the graph? It will not come back when sources are indexed again.', {
          name: d.name,
        }),
      )
    ) {
      return Promise.resolve();
    }
    const scope = this.scopeId()!;
    return this.edited(() => this.graphApi.deleteEntity(d.id, scope), null);
  }

  addRelation(d: EntityDetail): Promise<void> {
    const scope = this.scopeId()!;
    const target = this.relTarget!;
    return this.edited(
      () => this.graphApi.addRelation(scope, d.id, target, this.relType.trim(), ''),
      d.id,
    );
  }

  removeRelation(relationId: string): Promise<void> {
    const scope = this.scopeId()!;
    const id = this.entityId();
    return this.edited(() => this.graphApi.deleteRelation(relationId, scope), id);
  }
}
