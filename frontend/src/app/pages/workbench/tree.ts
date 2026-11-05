import { GrantRole, NodeKind, TreeNodeDto } from '../../core/api.models';

export interface TreeItem {
  node: TreeNodeDto;
  children: TreeItem[];
}

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

/** Builds a nested tree from the flat, depth-ordered list returned by GET /api/nodes. */
export function buildTree(nodes: TreeNodeDto[]): TreeItem[] {
  const items = new Map<string, TreeItem>();
  for (const n of nodes) items.set(n.id, { node: n, children: [] });
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
