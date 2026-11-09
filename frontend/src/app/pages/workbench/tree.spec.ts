import { TreeNodeDto } from '../../core/api.models';
import { SourceDto } from '../../core/sources.api';
import { CHILD_KINDS, breadcrumb, buildTree, hasRole } from './tree';

const node = (
  id: string,
  parent: string | null,
  kind: TreeNodeDto['kind'],
  role: TreeNodeDto['role'] = 'owner',
): TreeNodeDto => ({
  id,
  parent_id: parent,
  kind,
  name: id,
  slug: id,
  depth: 0,
  active: true,
  role,
  project_id: 'wifi',
});

describe('tree helpers', () => {
  const flat = [
    node('wifi', null, 'project', null),
    node('source', 'wifi', 'workspace'),
    node('docs', 'wifi', 'workspace'),
    node('modules', 'source', 'workspace'),
    node('driver', 'modules', 'notebook', 'viewer'),
  ];

  it('builds a nested, sorted tree with free nesting', () => {
    const roots = buildTree(flat);
    expect(roots.map((r) => r.node.id)).toEqual(['wifi']);
    expect(roots[0].children.map((c) => c.node.id)).toEqual(['docs', 'source']);
    expect(roots[0].children[1].children[0].children[0].node.id).toBe('driver');
  });

  it('adds sources as leaves after the sub-nodes of their notebook', () => {
    const nb = node('nb', 'source', 'notebook');
    const sub = node('child', 'nb', 'notebook');
    const src = { id: 'x', notebook_id: 'nb', title: 'a.pdf' } as never;
    const roots = buildTree(
      [node('wifi', null, 'project'), node('source', 'wifi', 'workspace'), nb, sub],
      [src],
    );
    const nbItem = roots[0].children[0].children[0];
    expect(nbItem.children.map((c) => c.key)).toEqual(['child', 's:x']);
    expect(nbItem.children[1].source?.title).toBe('a.pdf');
  });

  it('computes the breadcrumb of the selected scope', () => {
    expect(breadcrumb(flat, 'driver').map((n) => n.id)).toEqual([
      'wifi',
      'source',
      'modules',
      'driver',
    ]);
    expect(breadcrumb(flat, null)).toEqual([]);
  });

  it('checks roles and allowed child kinds', () => {
    expect(hasRole(flat[4], 'viewer')).toBe(true);
    expect(hasRole(flat[4], 'editor')).toBe(false);
    expect(hasRole(flat[0], 'viewer')).toBe(false); // ancestor shown for navigation only
    expect(CHILD_KINDS.notebook).toEqual(['notebook']);
  });

  it('nests archive members and crawled pages under their parent source', () => {
    const src = (id: string, parent: string | null) =>
      ({ id, notebook_id: 'driver', parent_source_id: parent, title: id }) as SourceDto;
    const tree = buildTree(flat, [src('fw.zip', null), src('a.c', 'fw.zip'), src('b.c', 'fw.zip')]);
    const driver = tree[0].children[1].children[0].children[0];
    expect(driver.children.map((c) => c.key)).toEqual(['s:fw.zip']);
    expect(driver.children[0].children.map((c) => c.source!.id)).toEqual(['a.c', 'b.c']);
  });

  it('attaches sources to projects and workspaces too', () => {
    const src = (id: string, nodeId: string) =>
      ({ id, notebook_id: nodeId, parent_source_id: null, title: id }) as SourceDto;
    const tree = buildTree(flat, [src('policy.md', 'wifi'), src('arch.md', 'source')]);
    expect(tree[0].children.map((c) => c.key)).toContain('s:policy.md');
    const sourceWs = tree[0].children.find((c) => c.key === 'source')!;
    expect(sourceWs.children.map((c) => c.key)).toContain('s:arch.md');
  });
});
