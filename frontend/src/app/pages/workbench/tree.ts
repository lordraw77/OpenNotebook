import { GrantRole, NodeKind, TreeNodeDto } from '../../core/api.models';
import { SourceDto } from '../../core/sources.api';

/** A tree row: a hierarchy node, or a source leaf (then `node` is the notebook that contains it). */
export interface TreeItem {
  key: string;
  node: TreeNodeDto;
  source?: SourceDto;
  children: TreeItem[];
}

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

const RANK: Record<GrantRole, number> = { viewer: 1, editor: 2, owner: 3 };

export function hasRole(node: TreeNodeDto, min: GrantRole): boolean {
  return node.role !== null && RANK[node.role] >= RANK[min];
}

/** Builds a nested tree from GET /api/nodes; sources become leaves after the sub-nodes of their notebook. */
export function buildTree(nodes: TreeNodeDto[], sources: SourceDto[] = []): TreeItem[] {
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
  // Archive members and crawled pages are nested under their parent source.
  const bySource = [...sources].sort((a, b) => a.title.localeCompare(b.title));
  const sourceItems = new Map<string, TreeItem>();
  for (const src of bySource) {
    const notebook = items.get(src.notebook_id);
    if (notebook)
      sourceItems.set(src.id, {
        key: `s:${src.id}`,
        node: notebook.node,
        source: src,
        children: [],
      });
  }
  for (const item of sourceItems.values()) {
    const parentId = item.source!.parent_source_id;
    const parent = parentId ? sourceItems.get(parentId) : undefined;
    (parent ?? items.get(item.source!.notebook_id)!).children.push(item);
  }
  return roots;
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
