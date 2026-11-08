import { bounds, layoutGraph } from './graph-layout';

describe('graph layout', () => {
  it('places every node, resolves edges and is deterministic', () => {
    const nodes = ['a', 'b', 'c'].map((id, i) => ({
      id,
      name: id.toUpperCase(),
      type: 'concept',
      mentions: i + 1,
      sources: 1,
    }));
    const edges = [
      { source: 'a', target: 'b', type: 'uses', weight: 1 },
      { source: 'b', target: 'missing', type: 'uses', weight: 1 },
    ];
    const first = layoutGraph(nodes, edges);
    const second = layoutGraph(nodes, edges);
    expect(first.edges.length).toBe(1);
    expect(first.edges[0].source.name).toBe('A');
    expect(first.nodes.every((n) => Number.isFinite(n.x) && Number.isFinite(n.y))).toBe(true);
    expect(first.nodes.map((n) => n.x)).toEqual(second.nodes.map((n) => n.x));
    const [, , w, h] = bounds(first.nodes);
    expect(w).toBeGreaterThan(120);
    expect(h).toBeGreaterThan(120);
  });
});
