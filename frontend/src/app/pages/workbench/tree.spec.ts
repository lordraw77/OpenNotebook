import { TreeNodeDto } from '../../core/api.models';
import { SourceDto } from '../../core/sources.api';
import { CHILD_KINDS, SourcePage, breadcrumb, buildTree, hasRole, sourceIcon } from './tree';

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
      pages({ nb: [src] }),
    );
    const nbItem = roots[0].children[0].children[0];
    expect(nbItem.children.map((c) => c.key)).toEqual(['child', 's:x']);
    expect(nbItem.children[1].source?.title).toBe('a.pdf');
  });

  it('picks icons by kind and document type', () => {
    const file = (mime: string) => ({ kind: 'file', mime_type: mime }) as SourceDto;
    expect(sourceIcon(file('application/vnd.ms-powerpoint'))).toBe('slideshow');
    expect(sourceIcon(file('application/vnd.oasis.opendocument.spreadsheet'))).toBe('table_chart');
    expect(sourceIcon(file('application/pdf'))).toBe('picture_as_pdf');
    expect(sourceIcon({ kind: 'code', mime_type: 'text/plain' } as SourceDto)).toBe('code');
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
    const tree = buildTree(
      flat,
      pages({ driver: [src('fw.zip', 'driver', 2)], 's:fw.zip': [src('a.c'), src('b.c')] }),
    );
    const driver = tree[0].children[1].children[0].children[0];
    expect(driver.children.map((c) => c.key)).toEqual(['s:fw.zip']);
    expect(driver.children[0].children.map((c) => c.source!.id)).toEqual(['a.c', 'b.c']);
  });

  it('attaches sources to projects and workspaces too', () => {
    const tree = buildTree(
      flat,
      pages({ wifi: [src('policy.md', 'wifi')], source: [src('arch.md', 'source')] }),
    );
    expect(tree[0].children.map((c) => c.key)).toContain('s:policy.md');
    const sourceWs = tree[0].children.find((c) => c.key === 'source')!;
    expect(sourceWs.children.map((c) => c.key)).toContain('s:arch.md');
  });

  it('adds placeholders for unloaded lists and further pages', () => {
    const tree = buildTree(
      flat,
      new Map<string, SourcePage>([['driver', { items: [src('fw.zip', 'driver', 40)], total: 3 }]]),
      { driver: 3, docs: 5, source: 0 },
    );
    const docs = tree[0].children[0];
    expect(docs.children.map((c) => c.key)).toEqual(['loading:docs']);
    expect(docs.children[0].placeholder).toBe('loading');
    const driver = tree[0].children[1].children[0].children[0];
    expect(driver.children.map((c) => c.key)).toEqual(['s:fw.zip', 'more:driver']);
    // the archive has members but its page is not loaded yet
    expect(driver.children[0].children.map((c) => c.key)).toEqual(['loading:s:fw.zip']);
    expect(driver.children[1].owner).toBe('driver');
    // the workspace "source" has sub-nodes only: no placeholder
    expect(tree[0].children[1].children.map((c) => c.key)).toEqual(['modules']);
  });
});

function src(id: string, nodeId = 'driver', childCount = 0): SourceDto {
  return {
    id,
    notebook_id: nodeId,
    parent_source_id: null,
    title: id,
    child_count: childCount,
  } as SourceDto;
}

function pages(byKey: Record<string, SourceDto[]>): Map<string, SourcePage> {
  return new Map(Object.entries(byKey).map(([k, items]) => [k, { items, total: items.length }]));
}
