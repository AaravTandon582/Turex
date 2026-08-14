"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { NODE_STYLES, type Graph, type GraphNode } from "@/lib/discovery";

interface Placed extends GraphNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
  degree: number;
}

const WIDTH = 900;
const HEIGHT = 620;
const ITERATIONS = 260;

/**
 * A force-directed layout of the knowledge graph, drawn as inline SVG.
 *
 * The simulation runs once, synchronously, before the first paint rather than animating: a
 * settled layout is what the reader wants to look at, and thirty seconds of drifting nodes is
 * a distraction rather than a feature. At this scale — tens of nodes — the whole run takes a
 * few milliseconds.
 *
 * No charting library: this is one specific diagram with one specific interaction, and a
 * general-purpose graph package would cost more bundle than the code it replaces.
 */
export function ForceGraph({
  graph,
  onSelect,
}: {
  graph: Graph;
  onSelect: (node: GraphNode | null) => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const layout = useMemo(() => simulate(graph), [graph]);

  useEffect(() => {
    // Clear the selection when the graph itself changes, so a stale node cannot stay
    // highlighted after it has gone.
    setSelectedId(null);
    onSelect(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph]);

  const byId = new Map(layout.map((node) => [node.id, node]));
  const neighbours = new Set<string>();
  if (selectedId) {
    for (const edge of graph.edges) {
      if (edge.source === selectedId) neighbours.add(edge.target);
      if (edge.target === selectedId) neighbours.add(edge.source);
    }
  }

  function isDimmed(id: string): boolean {
    return selectedId !== null && id !== selectedId && !neighbours.has(id);
  }

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className="h-full w-full"
      role="img"
      aria-label={`Knowledge graph with ${graph.nodes.length} nodes`}
      onClick={(event) => {
        // A click on empty canvas clears the selection.
        if (event.target === svgRef.current) {
          setSelectedId(null);
          onSelect(null);
        }
      }}
    >
      <g>
        {graph.edges.map((edge, index) => {
          const source = byId.get(edge.source);
          const target = byId.get(edge.target);
          if (!source || !target) return null;

          const dimmed = isDimmed(edge.source) || isDimmed(edge.target);
          return (
            <line
              key={index}
              x1={source.x}
              y1={source.y}
              x2={target.x}
              y2={target.y}
              stroke="var(--border-strong)"
              strokeWidth={edge.kind === "mentions" ? 1 : 1.5}
              strokeOpacity={dimmed ? 0.12 : 0.5}
              strokeDasharray={edge.kind === "asks" ? "3 3" : undefined}
            />
          );
        })}
      </g>

      <g>
        {layout.map((node) => {
          const style = NODE_STYLES[node.kind];
          const radius = 6 + Math.min(node.degree, 8) * 1.4 + node.weight;
          const dimmed = isDimmed(node.id);

          return (
            <g
              key={node.id}
              transform={`translate(${node.x} ${node.y})`}
              opacity={dimmed ? 0.25 : 1}
              className="cursor-pointer"
              onClick={() => {
                const next = selectedId === node.id ? null : node;
                setSelectedId(next?.id ?? null);
                onSelect(next);
              }}
            >
              <circle
                r={radius}
                fill={style.fill}
                stroke={style.stroke}
                strokeWidth={selectedId === node.id ? 2.5 : 1.25}
              />
              <text
                y={radius + 11}
                textAnchor="middle"
                fill={style.text}
                fontSize={node.kind === "paper" ? 10.5 : 9.5}
                className="pointer-events-none select-none"
              >
                {truncate(node.label, node.kind === "concept" ? 22 : 30)}
              </text>
            </g>
          );
        })}
      </g>
    </svg>
  );
}

function truncate(value: string, limit: number): string {
  return value.length <= limit ? value : `${value.slice(0, limit - 1)}…`;
}

/**
 * Fruchterman–Reingold style layout: every node repels every other, edges pull their
 * endpoints together, and a cooling schedule settles the result.
 */
function simulate(graph: Graph): Placed[] {
  const degree = new Map<string, number>();
  for (const edge of graph.edges) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  }

  // Seeded from the node's index on a circle rather than randomly, so the same graph always
  // lays out the same way. A diagram that rearranges itself on every visit is unreadable.
  const nodes: Placed[] = graph.nodes.map((node, index) => {
    const angle = (index / Math.max(1, graph.nodes.length)) * Math.PI * 2;
    const spread = 140 + (index % 5) * 40;
    return {
      ...node,
      x: WIDTH / 2 + Math.cos(angle) * spread,
      y: HEIGHT / 2 + Math.sin(angle) * spread,
      vx: 0,
      vy: 0,
      degree: degree.get(node.id) ?? 0,
    };
  });

  if (nodes.length === 0) return nodes;

  const index = new Map(nodes.map((node) => [node.id, node]));
  const area = WIDTH * HEIGHT;
  const ideal = Math.sqrt(area / nodes.length) * 0.55;
  let temperature = WIDTH / 8;

  for (let step = 0; step < ITERATIONS; step += 1) {
    for (const node of nodes) {
      node.vx = 0;
      node.vy = 0;
    }

    // Repulsion between every pair.
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const a = nodes[i];
        const b = nodes[j];
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let distance = Math.hypot(dx, dy);
        if (distance < 0.01) {
          // Coincident nodes would divide by zero; nudge them apart deterministically.
          dx = (i - j) * 0.01 || 0.01;
          dy = 0.01;
          distance = Math.hypot(dx, dy);
        }
        const force = (ideal * ideal) / distance;
        const fx = (dx / distance) * force;
        const fy = (dy / distance) * force;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      }
    }

    // Attraction along edges.
    for (const edge of graph.edges) {
      const source = index.get(edge.source);
      const target = index.get(edge.target);
      if (!source || !target) continue;

      const dx = source.x - target.x;
      const dy = source.y - target.y;
      const distance = Math.max(0.01, Math.hypot(dx, dy));
      const force = (distance * distance) / ideal;
      const fx = (dx / distance) * force;
      const fy = (dy / distance) * force;
      source.vx -= fx;
      source.vy -= fy;
      target.vx += fx;
      target.vy += fy;
    }

    for (const node of nodes) {
      const speed = Math.max(0.01, Math.hypot(node.vx, node.vy));
      node.x += (node.vx / speed) * Math.min(speed, temperature);
      node.y += (node.vy / speed) * Math.min(speed, temperature);
      // Keep everything inside the viewport, with room for the label under each node.
      node.x = Math.min(WIDTH - 60, Math.max(60, node.x));
      node.y = Math.min(HEIGHT - 40, Math.max(40, node.y));
    }

    temperature *= 0.975;
  }

  return nodes;
}
