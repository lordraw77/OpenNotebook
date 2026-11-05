import { TreeNodeDto } from '../../core/api.models';
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
});
