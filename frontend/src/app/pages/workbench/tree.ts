import { GrantRole, NodeKind, TreeNodeDto } from '../../core/api.models';
import { t } from '../../core/i18n';
import { SourceDto } from '../../core/sources.api';

/**
 * A tree row: a hierarchy node, a source leaf (then `node` is the node that contains it), or a placeholder row of
 * a lazily loaded list (`loading` before the first page arrives, `more` when further pages exist).
 */
export interface TreeItem {
  key: string;
  node: TreeNodeDto;
  source?: SourceDto;
  placeholder?: 'loading' | 'more';
  /** Key of the item whose list the placeholder belongs to. */
  owner?: string;
  children: TreeItem[];
}

/** A loaded slice of the sources of a node (key = node id) or of an archive/crawl (key = `s:<source id>`). */
export interface SourcePage {
  items: SourceDto[];
  total: number;
}

export const sourceKey = (id: string) => `s:${id}`;

export const SOURCE_ICONS: Record<string, string> = {
  file: 'description',
  note: 'sticky_note_2',
  code: 'code',
  image: 'image',
  web: 'language',
  archive: 'folder_zip',
};

/** Kinds that may be created under a parent kind (mirrors backend ALLOWED_PARENTS). */
export const CHILD_KINDS: Record<NodeKind, NodeKind[]> = {
  project: ['workspace', 'notebook'],
  workspace: ['workspace', 'notebook'],
  notebook: ['notebook'],
};

export const KIND_ICONS: Record<NodeKind, string> = {
  project: 'folder_special',
  workspace: 'folder',
  notebook: 'menu_book',
};

/** Icon of a source row: by kind, refined by document type for files (slides, spreadsheets, PDF). */
export function sourceIcon(src: SourceDto): string {
  const mime = src.mime_type ?? '';
  if (src.kind === 'file') {
    if (/presentation|powerpoint/.test(mime)) return 'slideshow';
    if (/spreadsheet|excel/.test(mime)) return 'table_chart';
    if (mime === 'application/pdf') return 'picture_as_pdf';
  }
  return SOURCE_ICONS[src.kind] ?? 'description';
}

/** Translated name of a node kind (evaluated at call time: the language is set before bootstrap). */
export function kindLabel(kind: NodeKind): string {
  return { project: t('project'), workspace: t('workspace'), notebook: t('notebook') }[kind];
}

export function newKindLabel(kind: NodeKind): string {
  return { project: t('New project'), workspace: t('New workspace'), notebook: t('New notebook') }[
    kind
  ];
}

const RANK: Record<GrantRole, number> = { viewer: 1, editor: 2, owner: 3 };

export function hasRole(node: TreeNodeDto, min: GrantRole): boolean {
  return node.role !== null && RANK[node.role] >= RANK[min];
}

/**
 * Builds the nested tree from GET /api/nodes. Sources come from the loaded pages and are listed after the
 * sub-nodes of their node; members of an archive and crawled pages nest under their parent source. A node with
 * sources (`counts`) or a source with members whose page is not loaded yet gets a `loading` child, so it can be
 * expanded (expanding it loads the page).
 */
export function buildTree(
  nodes: TreeNodeDto[],
  pages: ReadonlyMap<string, SourcePage> = new Map(),
  counts: Readonly<Record<string, number>> = {},
): TreeItem[] {
  const items = new Map<string, TreeItem>();
  for (const n of nodes) items.set(n.id, { key: n.id, node: n, children: [] });
  const roots: TreeItem[] = [];
  for (const item of items.values()) {
    const parent = item.node.parent_id ? items.get(item.node.parent_id) : undefined;
    (parent ? parent.children : roots).push(item);
  }
  const sort = (list: TreeItem[]) => {
    list.sort((a, b) => a.node.name.localeCompare(b.node.name));
    list.forEach((i) => sort(i.children));
  };
  sort(roots);

  const attach = (
    owner: TreeItem,
    node: TreeNodeDto,
    expected: number,
    seen: Set<string>,
  ): void => {
    const page = pages.get(owner.key);
    if (!page) {
      if (expected > 0) owner.children.push(placeholder('loading', owner.key, node));
      return;
    }
    for (const src of page.items) {
      const key = sourceKey(src.id);
      if (seen.has(key)) continue; // a source cannot contain itself; guards against inconsistent pages
      seen.add(key);
      const child: TreeItem = { key, node, source: src, children: [] };
      attach(child, node, src.child_count ?? 0, seen);
      owner.children.push(child);
    }
    if (page.items.length < page.total) owner.children.push(placeholder('more', owner.key, node));
  };
  const seen = new Set<string>();
  for (const item of items.values()) attach(item, item.node, counts[item.node.id] ?? 0, seen);
  return roots;
}

function placeholder(kind: 'loading' | 'more', owner: string, node: TreeNodeDto): TreeItem {
  return { key: `${kind}:${owner}`, node, placeholder: kind, owner, children: [] };
}

/** Path of names from the root to the node, used as breadcrumb for the selected scope. */
export function breadcrumb(nodes: TreeNodeDto[], id: string | null): TreeNodeDto[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const out: TreeNodeDto[] = [];
  let cur = id ? byId.get(id) : undefined;
  while (cur) {
    out.unshift(cur);
    cur = cur.parent_id ? byId.get(cur.parent_id) : undefined;
  }
  return out;
}
