"use client";

import { Share2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { ForceGraph } from "@/components/graph/force-graph";
import { PageContainer } from "@/components/layout/page-container";
import { Card, EmptyState, PageHeader, Skeleton } from "@/components/ui/primitives";
import { discovery, NODE_STYLES, type Graph, type GraphNode } from "@/lib/discovery";

export default function GraphPage() {
  const [graph, setGraph] = useState<Graph | null>(null);
  const [selected, setSelected] = useState<GraphNode | null>(null);

  useEffect(() => {
    void discovery
      .graph()
      .then(setGraph)
      .catch(() => setGraph({ nodes: [], edges: [] }));
  }, []);

  const papers = graph?.nodes.filter((node) => node.kind === "paper").length ?? 0;
  const concepts = graph?.nodes.filter((node) => node.kind === "concept").length ?? 0;

  return (
    <PageContainer width="full">
      <PageHeader
        title="Knowledge graph"
        description="How the papers in your library actually connect — through the terms they share, the projects gathering them, and the questions you are asking."
      />

      {!graph ? (
        <Skeleton className="mt-6 h-[620px] w-full rounded-lg" />
      ) : graph.nodes.length === 0 ? (
        <EmptyState
          className="mt-6"
          icon={<Share2 />}
          title="Nothing to connect yet"
          description="Add a few papers to your library. Once two of them use the same terms, Atlas draws the link — from the text itself, not from a guess."
        />
      ) : (
        <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,1fr)_260px]">
          <Card className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-border px-4 py-2">
              <p className="text-[12px] text-ink-muted" data-tabular>
                {papers} papers · {concepts} shared concepts · {graph.edges.length} links
              </p>
              <p className="text-[12px] text-ink-subtle">Click a node to trace it</p>
            </div>
            <div className="h-[560px]">
              <ForceGraph graph={graph} onSelect={setSelected} />
            </div>
          </Card>

          <div className="space-y-4">
            <Card className="p-3">
              <h2 className="text-[12px] font-semibold text-ink-muted">Legend</h2>
              <ul className="mt-2 space-y-1.5">
                {Object.entries(NODE_STYLES).map(([kind, style]) => (
                  <li key={kind} className="flex items-center gap-2 text-[12px] text-ink-muted">
                    <span
                      aria-hidden
                      className="size-3 shrink-0 rounded-full border"
                      style={{ background: style.fill, borderColor: style.stroke }}
                    />
                    {style.label}
                  </li>
                ))}
              </ul>
            </Card>

            <Card className="p-3">
              <h2 className="text-[12px] font-semibold text-ink-muted">Selection</h2>
              {selected ? (
                <NodeDetail node={selected} graph={graph} />
              ) : (
                <p className="mt-2 text-[12px] leading-relaxed text-ink-subtle">
                  Select a node to see what it connects to. An edge between two papers means
                  they genuinely use the same term — nothing here is inferred.
                </p>
              )}
            </Card>
          </div>
        </div>
      )}
    </PageContainer>
  );
}

function NodeDetail({ node, graph }: { node: GraphNode; graph: Graph }) {
  const connectedIds = new Set<string>();
  for (const edge of graph.edges) {
    if (edge.source === node.id) connectedIds.add(edge.target);
    if (edge.target === node.id) connectedIds.add(edge.source);
  }
  const connected = graph.nodes.filter((other) => connectedIds.has(other.id));

  return (
    <div className="mt-2">
      <p className="text-[11px] font-semibold tracking-wide text-ink-subtle uppercase">
        {NODE_STYLES[node.kind].label}
      </p>
      <p className="mt-0.5 text-[13px] leading-snug text-ink">{node.label}</p>

      {node.kind === "paper" && node.entity_id && (
        <Link
          href={`/library/${node.entity_id}`}
          className="mt-1.5 inline-block text-[12px] font-medium text-accent hover:underline"
        >
          Open the paper
        </Link>
      )}
      {node.kind === "project" && node.entity_id && (
        <Link
          href={`/projects/${node.entity_id}`}
          className="mt-1.5 inline-block text-[12px] font-medium text-accent hover:underline"
        >
          Open the project
        </Link>
      )}

      <p className="mt-3 text-[11px] font-semibold tracking-wide text-ink-subtle uppercase">
        Connects to {connected.length}
      </p>
      <ul className="mt-1 space-y-1">
        {connected.slice(0, 10).map((other) => (
          <li key={other.id} className="flex items-start gap-1.5 text-[12px] text-ink-muted">
            <span
              aria-hidden
              className="mt-1 size-2 shrink-0 rounded-full border"
              style={{
                background: NODE_STYLES[other.kind].fill,
                borderColor: NODE_STYLES[other.kind].stroke,
              }}
            />
            <span className="min-w-0">{other.label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
