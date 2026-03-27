import { useState } from "react";
import { GitFork, BarChart3, Code2 } from "lucide-react";
import { useGraphQuery } from "../api/hooks";
import { useI18n } from "../i18n/context";
import JsonView from "../components/JsonView";
import GraphFlowChart from "../components/GraphFlowChart";

type QueryType =
  | "call_chain"
  | "inheritance_tree"
  | "class_methods"
  | "module_dependencies"
  | "reverse_dependencies"
  | "find_entity"
  | "file_entities"
  | "graph_stats"
  | "raw_cypher";

interface FieldConfig {
  showName?: boolean;
  nameKey?: string;
  showFile?: boolean;
  showDepth?: boolean;
  showDirection?: boolean;
  showEntityType?: boolean;
  showCypher?: boolean;
}

const FIELD_MAP: Record<QueryType, FieldConfig> = {
  call_chain: { showName: true, nameKey: "functionName", showDepth: true, showDirection: true },
  inheritance_tree: { showName: true, nameKey: "className" },
  class_methods: { showName: true, nameKey: "className" },
  module_dependencies: { showName: true, nameKey: "moduleName" },
  reverse_dependencies: { showName: true, nameKey: "entityName" },
  find_entity: { showName: true, nameKey: "entityName", showEntityType: true },
  file_entities: { showFile: true },
  graph_stats: {},
  raw_cypher: { showCypher: true },
};

export default function GraphQuery() {
  const [queryType, setQueryType] = useState<QueryType>("call_chain");
  const [name, setName] = useState("");
  const [file, setFile] = useState("");
  const [depth, setDepth] = useState(3);
  const [direction, setDirection] = useState("downstream");
  const [entityType, setEntityType] = useState("any");
  const [cypher, setCypher] = useState("");

  const { t } = useI18n();
  const mutation = useGraphQuery();
  const fields = FIELD_MAP[queryType];

  const QUERY_TYPES: { value: QueryType; label: string }[] = [
    { value: "call_chain", label: t.graph.callChain },
    { value: "inheritance_tree", label: t.graph.inheritanceTree },
    { value: "class_methods", label: t.graph.classMethods },
    { value: "module_dependencies", label: t.graph.moduleDeps },
    { value: "reverse_dependencies", label: t.graph.reverseDeps },
    { value: "find_entity", label: t.graph.findEntity },
    { value: "file_entities", label: t.graph.fileEntities },
    { value: "graph_stats", label: t.graph.graphStats },
    { value: "raw_cypher", label: t.graph.customCypher },
  ];

  const nameLabel = fields.nameKey
    ? t.graph[fields.nameKey as keyof typeof t.graph] || fields.nameKey
    : "";

  function runQuery(overrideName?: string) {
    mutation.mutate({
      query_type: queryType,
      name: overrideName ?? name,
      file,
      depth,
      direction,
      entity_type: entityType,
      cypher,
    });
  }

  function handleRun(e: React.FormEvent) {
    e.preventDefault();
    runQuery();
  }

  function handleNodeDrillDown(nodeName: string) {
    setName(nodeName);
    setTimeout(() => {
      mutation.mutate({
        query_type: queryType,
        name: nodeName,
        file,
        depth,
        direction,
        entity_type: entityType,
        cypher,
      });
    }, 0);
  }

  const inputClass =
    "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-sky-400 focus:ring-1 focus:ring-sky-300";

  return (
    <div className="space-y-6">
      <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900">
        <GitFork size={20} /> {t.graph.title}
      </h2>

      <form
        onSubmit={handleRun}
        className="space-y-4 rounded-xl border border-gray-200 bg-white p-5"
      >
        <label className="block text-xs font-medium text-gray-500">
          {t.graph.queryType}
          <select
            value={queryType}
            onChange={(e) => setQueryType(e.target.value as QueryType)}
            className={`mt-1 ${inputClass}`}
          >
            {QUERY_TYPES.map((qt) => (
              <option key={qt.value} value={qt.value}>
                {qt.label}
              </option>
            ))}
          </select>
        </label>

        {fields.showName && (
          <label className="block text-xs font-medium text-gray-500">
            {nameLabel}
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={nameLabel}
              className={`mt-1 ${inputClass}`}
            />
          </label>
        )}

        {fields.showFile && (
          <label className="block text-xs font-medium text-gray-500">
            {t.graph.filePath}
            <input
              type="text"
              value={file}
              onChange={(e) => setFile(e.target.value)}
              placeholder="e.g. src/main.py"
              className={`mt-1 ${inputClass}`}
            />
          </label>
        )}

        {fields.showDepth && (
          <label className="block text-xs font-medium text-gray-500">
            {t.graph.depth}
            <input
              type="number"
              min={1}
              max={10}
              value={depth}
              onChange={(e) => setDepth(Number(e.target.value) || 3)}
              className={`mt-1 w-24 ${inputClass}`}
            />
          </label>
        )}

        {fields.showDirection && (
          <label className="block text-xs font-medium text-gray-500">
            {t.graph.direction}
            <select
              value={direction}
              onChange={(e) => setDirection(e.target.value)}
              className={`mt-1 ${inputClass}`}
            >
              <option value="downstream">{t.graph.downstream}</option>
              <option value="upstream">{t.graph.upstream}</option>
            </select>
          </label>
        )}

        {fields.showEntityType && (
          <label className="block text-xs font-medium text-gray-500">
            {t.graph.entityType}
            <select
              value={entityType}
              onChange={(e) => setEntityType(e.target.value)}
              className={`mt-1 ${inputClass}`}
            >
              <option value="any">{t.graph.any}</option>
              <option value="function">{t.search.function}</option>
              <option value="class">{t.search.class}</option>
            </select>
          </label>
        )}

        {fields.showCypher && (
          <label className="block text-xs font-medium text-gray-500">
            {t.graph.cypherQuery}
            <textarea
              value={cypher}
              onChange={(e) => setCypher(e.target.value)}
              rows={4}
              placeholder="MATCH (n:Function) RETURN n LIMIT 10"
              className={`mt-1 resize-y font-mono ${inputClass}`}
            />
          </label>
        )}

        <button
          type="submit"
          disabled={mutation.isPending}
          className="rounded-lg bg-sky-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:opacity-50"
        >
          {mutation.isPending ? t.graph.running : t.graph.runQuery}
        </button>
      </form>

      {mutation.error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-600">
          {mutation.error.message}
        </div>
      )}

      {mutation.data && <GraphQueryResult
        data={mutation.data}
        queryType={queryType}
        name={name}
        direction={direction}
        onNodeDrillDown={handleNodeDrillDown}
      />}
    </div>
  );
}

const VISUALIZABLE_TYPES = new Set([
  "call_chain", "inheritance_tree", "class_methods",
  "module_dependencies", "reverse_dependencies",
]);

function GraphQueryResult({
  data,
  queryType,
  name,
  direction,
  onNodeDrillDown,
}: {
  data: Record<string, unknown>;
  queryType: string;
  name: string;
  direction: string;
  onNodeDrillDown: (name: string) => void;
}) {
  const [viewMode, setViewMode] = useState<"chart" | "json">(
    VISUALIZABLE_TYPES.has(queryType) ? "chart" : "json"
  );
  const { t } = useI18n();

  const results = (data.results ?? data.methods ?? []) as Array<{
    name: string;
    file?: string;
    line?: number;
    type?: string;
  }>;
  const canVisualize = VISUALIZABLE_TYPES.has(queryType) && results.length > 0;

  return (
    <div className="space-y-3">
      {canVisualize && (
        <div className="flex gap-2">
          <button
            onClick={() => setViewMode("chart")}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
              viewMode === "chart"
                ? "bg-sky-100 text-sky-600"
                : "text-gray-400 hover:text-gray-700"
            }`}
          >
            <BarChart3 size={14} /> {t.graph.flowChart ?? "Flow Chart"}
          </button>
          <button
            onClick={() => setViewMode("json")}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
              viewMode === "json"
                ? "bg-purple-100 text-purple-600"
                : "text-gray-400 hover:text-gray-700"
            }`}
          >
            <Code2 size={14} /> JSON
          </button>
          <span className="ml-auto text-xs text-gray-400">
            {results.length} {t.graph.resultCount ?? "results"}
            {viewMode === "chart" && (
              <span className="ml-3 text-gray-500">
                {t.graph.doubleClickDrillDown ?? "Double-click node to drill down"}
              </span>
            )}
          </span>
        </div>
      )}

      {viewMode === "chart" && canVisualize ? (
        <GraphFlowChart
          queryType={queryType}
          rootName={name || String(data.function ?? data.class ?? data.module ?? "")}
          results={results}
          direction={direction}
          edges={(data.edges ?? []) as Array<{ source: string; target: string }>}
          onNodeDoubleClick={onNodeDrillDown}
        />
      ) : (
        <JsonView data={data} />
      )}
    </div>
  );
}
