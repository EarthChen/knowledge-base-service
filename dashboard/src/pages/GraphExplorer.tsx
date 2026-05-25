import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Panel,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Network, Search, ZoomIn, Loader2, AlertTriangle, Undo2 } from "lucide-react";
import ErrorBoundary from "../components/ErrorBoundary";
import BlastRadiusPanel from "./graph/BlastRadiusPanel";
import CommunitiesPanel from "./graph/CommunitiesPanel";
import GraphFilterBar from "./graph/GraphFilterBar";
import NodeDetailPanel from "./graph/NodeDetailPanel";
import { INPUT_CLASS, normalizeGraphType, paletteForTheme } from "./graph/graphLayout";
import { useGraphExplorerState } from "./graph/useGraphExplorerState";

// Re-export layout utilities for tests and external consumers
export { computeDagrePositions, applyNodeStyles, buildFlowNodesWithDagre } from "./graph/graphLayout";

export default function GraphExplorer() {
  const {
    t,
    isDark,
    searchName,
    setSearchName,
    depth,
    setDepth,
    limit,
    setLimit,
    handleSubmit,
    mutation,
    initialSliceHint,
    expandMutation,
    expandHistory,
    handleUndoExpand,
    blastNamesInput,
    setBlastNamesInput,
    blastDepth,
    setBlastDepth,
    blastRepo,
    setBlastRepo,
    blastMutation,
    handleBlastRadius,
    communityRepo,
    setCommunityRepo,
    communityMinSize,
    setCommunityMinSize,
    communitiesMutation,
    handleLoadCommunities,
    handleCommunityClick,
    selectedCommunityKey,
    reposQuery,
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onNodeClick,
    onNodeDoubleClick,
    containerRef,
    typeVisible,
    toggleType,
    showEdgeLabels,
    setShowEdgeLabels,
    legend,
    edgeLegend,
    selectedApiNode,
    businessId,
    wikiForEntity,
    handleExpandNeighbors,
  } = useGraphExplorerState();

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-gray-100">
          <Network size={20} /> {t.explorer.title}
        </h2>
        <div className="flex items-center gap-2 text-xs text-gray-400 dark:text-gray-500">
          <span>
            {nodes.filter((n) => !n.hidden).length} {t.explorer.nodes} · {edges.length}{" "}
            {t.explorer.edges}
          </span>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
        <label className="flex-1 min-w-[200px]">
          <span className="mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400">
            {t.explorer.entityName}
          </span>
          <div className="relative">
            <Search
              size={16}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 dark:text-gray-500"
            />
            <input
              type="text"
              value={searchName}
              onChange={(e) => setSearchName(e.target.value)}
              placeholder={t.explorer.searchPlaceholder}
              className={`w-full pl-9 ${INPUT_CLASS}`}
            />
          </div>
        </label>
        <label>
          <span className="mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400">{t.explorer.depth}</span>
          <input
            type="number"
            min={1}
            max={5}
            value={depth}
            onChange={(e) => setDepth(Number(e.target.value) || 2)}
            className={`w-20 ${INPUT_CLASS}`}
          />
        </label>
        <label>
          <span className="mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400">{t.explorer.limit}</span>
          <input
            type="number"
            min={10}
            max={500}
            step={10}
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value) || 100)}
            className={`w-24 ${INPUT_CLASS}`}
          />
        </label>
        <button
          type="submit"
          disabled={mutation.isPending || !searchName.trim()}
          className="flex items-center gap-2 rounded-lg bg-sky-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:opacity-50 dark:bg-sky-500 dark:hover:bg-sky-400"
        >
          {mutation.isPending ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <ZoomIn size={16} />
          )}
          {t.explorer.explore}
        </button>
      </form>

      {initialSliceHint && (
        <div className="flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700 dark:border-amber-900/80 dark:bg-amber-950/60 dark:text-amber-200">
          <AlertTriangle size={16} className="shrink-0" aria-hidden />
          {t.explorer.expandMoreHint}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 text-sm">
        {expandMutation.isPending ? (
          <span className="flex items-center gap-2 text-sky-600 dark:text-sky-400">
            <Loader2 size={16} className="animate-spin shrink-0" aria-hidden />
            {t.explorer.expanding}
          </span>
        ) : null}
        {expandHistory.length > 0 ? (
          <button
            type="button"
            onClick={handleUndoExpand}
            disabled={expandMutation.isPending}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-800 shadow-sm transition-colors hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700"
          >
            <Undo2 size={14} aria-hidden />
            {t.explorer.undoExpand}
          </button>
        ) : null}
        {expandHistory.length > 0 ? (
          <span className="text-xs text-gray-600 dark:text-gray-400">
            {t.explorer.expandedCount.replace(
              "{count}",
              String(expandHistory.reduce((a, b) => a + b.length, 0)),
            )}
          </span>
        ) : null}
      </div>

      {mutation.error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-600 dark:border-red-900 dark:bg-red-950/60 dark:text-red-300">
          {mutation.error.message}
        </div>
      )}

      {expandMutation.error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-600 dark:border-red-900 dark:bg-red-950/60 dark:text-red-300">
          {expandMutation.error.message}
        </div>
      )}

      <div ref={containerRef} className="flex min-h-[500px] flex-1 flex-col gap-3 lg:flex-row">
        <aside className="flex w-full shrink-0 flex-col gap-4 lg:w-80">
          <BlastRadiusPanel
            blastNamesInput={blastNamesInput}
            setBlastNamesInput={setBlastNamesInput}
            blastDepth={blastDepth}
            setBlastDepth={setBlastDepth}
            blastRepo={blastRepo}
            setBlastRepo={setBlastRepo}
            blastMutation={blastMutation}
            onRun={handleBlastRadius}
          />
          <CommunitiesPanel
            communityRepo={communityRepo}
            setCommunityRepo={setCommunityRepo}
            communityMinSize={communityMinSize}
            setCommunityMinSize={setCommunityMinSize}
            communitiesMutation={communitiesMutation}
            reposQuery={reposQuery}
            selectedCommunityKey={selectedCommunityKey}
            onLoad={handleLoadCommunities}
            onCommunityClick={handleCommunityClick}
          />
        </aside>

        <div className="flex min-h-[500px] min-w-0 flex-1 flex-col gap-2">
          {nodes.length > 0 ? (
            <>
              <GraphFilterBar
                typeVisible={typeVisible}
                toggleType={toggleType}
                showEdgeLabels={showEdgeLabels}
                setShowEdgeLabels={setShowEdgeLabels}
                legend={legend}
              />

              <div
                role="img"
                aria-label={t.explorer.canvasLabel}
                className="min-h-[480px] flex-1 overflow-hidden rounded-xl border border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-slate-900"
              >
                <ErrorBoundary fallbackLabel={t.explorer.graphRenderFailed}>
                <ReactFlow
                  nodes={nodes}
                  edges={edges}
                  onNodesChange={onNodesChange}
                  onEdgesChange={onEdgesChange}
                  onNodeClick={onNodeClick}
                  onNodeDoubleClick={onNodeDoubleClick}
                  fitView
                  fitViewOptions={{ padding: 0.3 }}
                  minZoom={0.1}
                  maxZoom={3}
                  proOptions={{ hideAttribution: true }}
                >
                  <Background color={isDark ? "#475569" : "#cbd5e1"} gap={20} />
                  <Controls
                    showInteractive={false}
                    style={
                      isDark
                        ? { background: "#1e293b", borderColor: "#334155" }
                        : { background: "#f8fafc", borderColor: "#e2e8f0" }
                    }
                  />
                  <MiniMap
                    nodeColor={(n) => {
                      const typ = normalizeGraphType((n.data?.type as string) || "");
                      const P = paletteForTheme(isDark);
                      return P[typ]?.border || "#64748b";
                    }}
                    style={
                      isDark
                        ? { background: "#0f172a", borderColor: "#334155" }
                        : { background: "#f1f5f9", borderColor: "#e2e8f0" }
                    }
                    maskColor={
                      isDark ? "rgba(15, 23, 42, 0.75)" : "rgba(241, 245, 249, 0.75)"
                    }
                  />

                  <Panel position="top-left" className="space-y-1.5">
                    <div className="rounded-lg border border-gray-200 bg-white/90 px-3 py-2 shadow-sm backdrop-blur dark:border-gray-600 dark:bg-gray-900/95">
                      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">
                        {t.explorer.nodeTypes}
                      </p>
                      <div className="flex flex-wrap gap-x-3 gap-y-1">
                        {legend.map((l) => (
                          <span
                            key={l.type}
                            className="flex items-center gap-1.5 text-[11px] text-gray-500 dark:text-gray-400"
                          >
                            <span
                              className="inline-block h-2.5 w-2.5 rounded-sm"
                              style={{ backgroundColor: l.color }}
                            />
                            {l.type}
                          </span>
                        ))}
                      </div>
                      <p className="mb-1.5 mt-2 text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">
                        {t.explorer.edgeTypes}
                      </p>
                      <div className="flex flex-wrap gap-x-3 gap-y-1">
                        {edgeLegend.map((l) => (
                          <span
                            key={l.type}
                            className="flex items-center gap-1.5 text-[11px] text-gray-500 dark:text-gray-400"
                          >
                            <span
                              className="inline-block h-0.5 w-4 rounded-full"
                              style={{ backgroundColor: l.color }}
                            />
                            {l.type}
                          </span>
                        ))}
                      </div>
                    </div>
                  </Panel>
                </ReactFlow>
                </ErrorBoundary>
              </div>
            </>
          ) : (
            <div className="flex min-h-[500px] flex-1 items-center justify-center rounded-xl border border-gray-200 bg-gray-50 text-gray-500 dark:border-gray-700 dark:bg-slate-900 dark:text-gray-400">
              <div className="text-center">
                <Network size={48} className="mx-auto mb-3 opacity-30 dark:opacity-40" aria-hidden />
                <p className="text-sm">{t.explorer.emptyHint}</p>
              </div>
            </div>
          )}
        </div>

        {selectedApiNode ? (
          <NodeDetailPanel
            node={selectedApiNode}
            isDark={isDark}
            businessId={businessId}
            wikiForEntity={wikiForEntity}
            expandMutation={expandMutation}
            onExpandNeighbors={handleExpandNeighbors}
          />
        ) : null}
      </div>
    </div>
  );
}
