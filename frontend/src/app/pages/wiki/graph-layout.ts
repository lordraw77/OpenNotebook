import {
  SimulationLinkDatum,
  SimulationNodeDatum,
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
} from 'd3-force';

import { EntityDto, GraphEdge } from '../../core/graph.api';

export interface LaidNode extends SimulationNodeDatum {
  id: string;
  name: string;
  type: string;
  mentions: number;
  r: number;
}

export interface LaidEdge {
  source: LaidNode;
  target: LaidNode;
  type: string;
}

/** Static force layout (computed once, no animation): node radius grows with the number of mentions. */
export function layoutGraph(
  nodes: EntityDto[],
  edges: GraphEdge[],
  ticks = 300,
): { nodes: LaidNode[]; edges: LaidEdge[] } {
  const laid: LaidNode[] = nodes.map((n, i) => ({
    id: n.id,
    name: n.name,
    type: n.type,
    mentions: n.mentions,
    r: 6 + Math.min(18, Math.sqrt(n.mentions) * 4),
    // deterministic start on a spiral (stable layouts between reloads)
    x: Math.cos(i) * 10 * Math.sqrt(i + 1),
    y: Math.sin(i) * 10 * Math.sqrt(i + 1),
  }));
  const byId = new Map(laid.map((n) => [n.id, n]));
  const links = edges
    .filter((e) => byId.has(e.source) && byId.has(e.target))
    .map((e) => ({ source: e.source, target: e.target, type: e.type }));
  const simulation = forceSimulation(laid)
    .force(
      'link',
      forceLink<LaidNode, SimulationLinkDatum<LaidNode>>(links)
        .id((d) => d.id)
        .distance(70),
    )
    .force('charge', forceManyBody().strength(-160))
    .force('center', forceCenter(0, 0))
    // weak gravity keeps disconnected clusters close instead of drifting apart
    .force('x', forceX(0).strength(0.08))
    .force('y', forceY(0).strength(0.08))
    .force(
      'collide',
      forceCollide<LaidNode>().radius((d) => d.r + 4),
    )
    .stop();
  simulation.tick(ticks);
  return {
    nodes: laid,
    edges: links.map((l) => ({
      source: l.source as unknown as LaidNode,
      target: l.target as unknown as LaidNode,
      type: l.type,
    })),
  };
}

/** Bounding box with a margin, for the SVG viewBox. */
export function bounds(nodes: LaidNode[], margin = 60): [number, number, number, number] {
  if (!nodes.length) return [-100, -100, 200, 200];
  const xs = nodes.map((n) => n.x ?? 0);
  const ys = nodes.map((n) => n.y ?? 0);
  const minX = Math.min(...xs) - margin;
  const minY = Math.min(...ys) - margin;
  return [minX, minY, Math.max(...xs) + margin - minX, Math.max(...ys) + margin - minY];
}
