/**
 * Knowledge Base Dashboard — vanilla JS SPA (matches static/index.html).
 * API: same-origin /api/v1/*
 */
(function () {
  "use strict";

  const STORAGE_KEY = "kb_api_token";
  const API_BASE = "/api/v1";

  /** UI query_type → backend `query_type` */
  const GRAPH_TYPE_MAP = {
    call_chain: "call_chain",
    inheritance: "inheritance_tree",
    class_methods: "class_methods",
    module_deps: "module_dependencies",
    reverse_dependencies: "reverse_dependencies",
    find_entity: "find_entity",
    file_entities: "file_entities",
    graph_stats: "graph_stats",
    custom: "raw_cypher",
  };

  let nodeChart = null;
  let edgeChart = null;

  function getToken() {
    return localStorage.getItem(STORAGE_KEY) || "";
  }

  function setToken(value) {
    if (value) localStorage.setItem(STORAGE_KEY, value);
    else localStorage.removeItem(STORAGE_KEY);
  }

  function authHeaders() {
    const t = getToken();
    const h = { "Content-Type": "application/json" };
    if (t) h.Authorization = "Bearer " + t;
    return h;
  }

  async function apiFetch(path, options) {
    const url = path.startsWith("http") ? path : API_BASE + path;
    const res = await fetch(url, {
      ...options,
      headers: { ...authHeaders(), ...(options.headers || {}) },
    });
    const text = await res.text();
    let data;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { raw: text };
    }
    if (!res.ok) {
      let msg = res.statusText;
      if (data && typeof data.detail === "string") msg = data.detail;
      else if (data && data.detail != null) msg = JSON.stringify(data.detail);
      else if (data && data.error) msg = String(data.error);
      const err = new Error(msg || "Request failed");
      err.status = res.status;
      err.body = data;
      throw err;
    }
    return data;
  }

  function showPage(page) {
    document.querySelectorAll(".page-content").forEach((p) => {
      p.classList.add("hidden");
    });
    const target = document.getElementById("page-" + page);
    if (target) target.classList.remove("hidden");

    document.querySelectorAll(".nav-item[data-page]").forEach((btn) => {
      const active = btn.getAttribute("data-page") === page;
      btn.classList.toggle("bg-slate-700/50", active);
      btn.classList.toggle("text-white", active);
      btn.classList.toggle("text-slate-400", !active);
      btn.setAttribute("aria-current", active ? "page" : "false");
    });

    if (page === "overview") loadOverview();
    if (page === "repositories") loadRepositories();

    var aside = document.getElementById("sidebar-nav");
    var toggle = document.getElementById("sidebar-toggle");
    if (
      aside &&
      toggle &&
      window.matchMedia &&
      window.matchMedia("(max-width: 1023px)").matches
    ) {
      aside.classList.add("hidden");
      aside.classList.remove("flex", "flex-col");
      toggle.setAttribute("aria-expanded", "false");
    }
  }

  async function checkHealth() {
    var dot = document.getElementById("health-dot");
    var label = document.getElementById("health-label");
    try {
      await apiFetch("/health", { method: "GET" });
      if (dot) {
        dot.className =
          "h-2.5 w-2.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)]";
      }
      if (label) label.textContent = "Healthy";
    } catch (e) {
      if (dot) {
        dot.className = "h-2.5 w-2.5 rounded-full bg-amber-500";
      }
      if (label) label.textContent = "Unreachable";
    }
  }

  function destroyCharts() {
    if (nodeChart) {
      nodeChart.destroy();
      nodeChart = null;
    }
    if (edgeChart) {
      edgeChart.destroy();
      edgeChart = null;
    }
  }

  function renderCharts(stats) {
    var nodeCtx = document.getElementById("chart-nodes");
    var edgeCtx = document.getElementById("chart-edges");
    if (!nodeCtx || !edgeCtx || typeof Chart === "undefined") return;

    destroyCharts();

    const nodeLabels = ["Function", "Class", "Module", "Document"];
    const nodeData = [
      stats.function_count || 0,
      stats.class_count || 0,
      stats.module_count || 0,
      stats.document_count || 0,
    ];

    nodeChart = new Chart(nodeCtx, {
      type: "doughnut",
      data: {
        labels: nodeLabels,
        datasets: [
          {
            data: nodeData,
            backgroundColor: [
              "rgba(16, 185, 129, 0.85)",
              "rgba(14, 165, 233, 0.85)",
              "rgba(168, 85, 247, 0.85)",
              "rgba(251, 191, 36, 0.85)",
            ],
            borderColor: "rgb(30 41 59)",
            borderWidth: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: "bottom",
            labels: { color: "rgb(203 213 225)", padding: 12, font: { size: 11 } },
          },
        },
      },
    });

    const edgeLabels = ["CALLS", "INHERITS", "IMPORTS", "CONTAINS", "REFERENCES"];
    const edgeData = [
      stats.calls_count || 0,
      stats.inherits_count || 0,
      stats.imports_count || 0,
      stats.contains_count || 0,
      stats.references_count || 0,
    ];

    edgeChart = new Chart(edgeCtx, {
      type: "bar",
      data: {
        labels: edgeLabels,
        datasets: [
          {
            label: "Count",
            data: edgeData,
            backgroundColor: "rgba(14, 165, 233, 0.7)",
            borderColor: "rgb(14, 165, 233)",
            borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            ticks: { color: "rgb(148 163 184)", font: { size: 10 } },
            grid: { color: "rgba(51, 65, 85, 0.4)" },
          },
          y: {
            beginAtZero: true,
            ticks: { color: "rgb(148 163 184)" },
            grid: { color: "rgba(51, 65, 85, 0.4)" },
          },
        },
        plugins: {
          legend: { display: false },
        },
      },
    });
  }

  async function loadOverview() {
    var errEl = document.getElementById("overview-error");
    if (errEl) errEl.classList.add("hidden");
    try {
      const stats = await apiFetch("/stats");
      var set = function (id, v) {
        var el = document.getElementById(id);
        if (el) el.textContent = v != null ? String(v) : "—";
      };
      set("stat-functions", stats.function_count);
      set("stat-classes", stats.class_count);
      set("stat-modules", stats.module_count);
      set("stat-documents", stats.document_count);
      set("edge-calls", stats.calls_count);
      set("edge-inherits", stats.inherits_count);
      set("edge-imports", stats.imports_count);
      set("edge-contains", stats.contains_count);
      set("edge-references", stats.references_count);
      renderCharts(stats);
    } catch (e) {
      if (errEl) {
        errEl.textContent = e.message || "Failed to load stats";
        errEl.classList.remove("hidden");
      }
    }
  }

  async function loadRepositories() {
    var tbody = document.getElementById("repos-tbody");
    var errEl = document.getElementById("repos-error");
    if (errEl) errEl.classList.add("hidden");
    if (!tbody) return;
    tbody.innerHTML =
      '<tr><td colspan="3" class="px-4 py-8 text-center text-slate-500">Loading…</td></tr>';
    try {
      const data = await apiFetch("/repositories");
      const repos = data.repositories || [];
      if (!repos.length) {
        tbody.innerHTML =
          '<tr><td colspan="3" class="px-4 py-8 text-center text-slate-500">No repositories indexed yet.</td></tr>';
        return;
      }
      tbody.innerHTML = "";
      repos.forEach(function (r) {
        var tr = document.createElement("tr");
        tr.className = "border-b border-slate-700/80 hover:bg-slate-800/40";
        tr.innerHTML =
          '<td class="px-4 py-3 font-medium text-slate-200">' +
          escapeHtml(r.repository) +
          '</td><td class="px-4 py-3 text-slate-400">' +
          r.nodes +
          '</td><td class="px-4 py-3 text-right">' +
          '<button type="button" class="delete-repo rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-1.5 text-sm text-red-400 hover:bg-red-500/20" data-repo="' +
          escapeAttr(r.repository) +
          '">Delete</button></td>';
        tbody.appendChild(tr);
      });
      tbody.querySelectorAll(".delete-repo").forEach(function (btn) {
        btn.addEventListener("click", function () {
          deleteRepository(btn.getAttribute("data-repo"));
        });
      });
    } catch (e) {
      tbody.innerHTML = "";
      if (errEl) {
        errEl.textContent = e.message || "Failed to load repositories";
        errEl.classList.remove("hidden");
      }
    }
  }

  async function deleteRepository(repo) {
    if (!repo || !confirm('Delete all indexed data for repository "' + repo + '"?')) return;
    try {
      await apiFetch("/index/" + encodeURIComponent(repo), { method: "DELETE" });
      loadRepositories();
    } catch (e) {
      alert(e.message || "Delete failed");
    }
  }

  async function runSearch() {
    var q = (document.getElementById("search-query") && document.getElementById("search-query").value) || "";
    q = q.trim();
    var entityType =
      (document.getElementById("search-entity-type") && document.getElementById("search-entity-type").value) ||
      "all";
    var k = parseInt(
      (document.getElementById("search-k") && document.getElementById("search-k").value) || "10",
      10
    );
    if (isNaN(k)) k = 10;
    var out = document.getElementById("search-results");
    var errEl = document.getElementById("search-error");
    if (errEl) errEl.classList.add("hidden");
    if (!out) return;
    if (!q) {
      if (errEl) {
        errEl.textContent = "Enter a search query.";
        errEl.classList.remove("hidden");
      }
      return;
    }
    out.innerHTML = '<p class="text-slate-500 py-8 text-center">Searching…</p>';
    try {
      const data = await apiFetch("/search", {
        method: "POST",
        body: JSON.stringify({ query: q, k: k, entity_type: entityType }),
      });
      const matches = data.matches || [];
      if (!matches.length) {
        out.innerHTML = '<p class="text-slate-500 py-8 text-center">No results.</p>';
        return;
      }
      out.innerHTML = "";
      matches.forEach(function (m) {
        var card = document.createElement("article");
        card.className = "rounded-xl border border-slate-700 bg-slate-800/80 p-4 shadow-lg";
        var type = escapeHtml(String(m.type || "unknown"));
        var name = escapeHtml(String(m.name || "—"));
        var file = escapeHtml(String(m.file || "—"));
        var line = m.line != null ? m.line : "—";
        var score = typeof m.score === "number" ? m.score.toFixed(4) : String(m.score != null ? m.score : "—");
        var sig = m.signature != null ? m.signature : "";
        var doc = m.docstring != null ? m.docstring : m.content || "";
        var extra = sig
          ? '<p class="mt-2 text-xs text-slate-500 font-mono">' + escapeHtml(sig) + "</p>"
          : "";
        var docBlock = doc
          ? '<p class="mt-2 text-sm text-slate-400 line-clamp-4">' + escapeHtml(doc) + "</p>"
          : "";
        card.innerHTML =
          '<div class="flex flex-wrap items-start justify-between gap-2">' +
          '<span class="inline-flex items-center rounded-md bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-400">' +
          type +
          "</span>" +
          '<span class="text-xs text-sky-400/90">score: ' +
          escapeHtml(score) +
          "</span></div>" +
          '<h3 class="mt-2 text-lg font-semibold text-white">' +
          name +
          "</h3>" +
          '<p class="mt-1 text-sm text-slate-400"><span class="text-slate-500">File:</span> ' +
          file +
          ' <span class="text-slate-600">·</span> line ' +
          line +
          "</p>" +
          extra +
          docBlock;
        out.appendChild(card);
      });
    } catch (e) {
      out.innerHTML = "";
      if (errEl) {
        errEl.textContent = e.message || "Search failed";
        errEl.classList.remove("hidden");
      }
    }
  }

  function updateGraphFormFields() {
    var sel = document.getElementById("graph-query-type");
    var v = sel ? sel.value : "call_chain";
    document.querySelectorAll("[data-graph-fields]").forEach(function (el) {
      var show = el.getAttribute("data-graph-fields") === v;
      el.classList.toggle("hidden", !show);
    });
  }

  function buildGraphPayload() {
    var uiType = document.getElementById("graph-query-type")
      ? document.getElementById("graph-query-type").value
      : "call_chain";
    var query_type = GRAPH_TYPE_MAP[uiType] || uiType;
    var payload = {
      query_type: query_type,
      name: "",
      file: "",
      depth: 3,
      direction: "downstream",
      cypher: "",
      entity_type: "any",
    };

    if (uiType === "call_chain") {
      payload.name = document.getElementById("gq-name-chain")
        ? document.getElementById("gq-name-chain").value.trim()
        : "";
      payload.depth = parseInt(
        document.getElementById("gq-depth") ? document.getElementById("gq-depth").value : "3",
        10
      ) || 3;
      payload.direction = document.getElementById("gq-direction")
        ? document.getElementById("gq-direction").value
        : "downstream";
    } else if (uiType === "inheritance") {
      payload.name = document.getElementById("gq-name-inherit")
        ? document.getElementById("gq-name-inherit").value.trim()
        : "";
    } else if (uiType === "class_methods") {
      payload.name = document.getElementById("gq-name-class")
        ? document.getElementById("gq-name-class").value.trim()
        : "";
    } else if (uiType === "module_deps") {
      payload.name = document.getElementById("gq-name-mod")
        ? document.getElementById("gq-name-mod").value.trim()
        : "";
    } else if (uiType === "reverse_dependencies") {
      payload.name = document.getElementById("gq-name-rev")
        ? document.getElementById("gq-name-rev").value.trim()
        : "";
    } else if (uiType === "find_entity") {
      payload.name = document.getElementById("gq-name-entity")
        ? document.getElementById("gq-name-entity").value.trim()
        : "";
      payload.entity_type = document.getElementById("gq-entity-type")
        ? document.getElementById("gq-entity-type").value
        : "any";
    } else if (uiType === "file_entities") {
      payload.file = document.getElementById("gq-file") ? document.getElementById("gq-file").value.trim() : "";
    } else if (uiType === "custom") {
      payload.cypher = document.getElementById("gq-cypher") ? document.getElementById("gq-cypher").value : "";
    }

    return payload;
  }

  async function runGraphQuery() {
    var out = document.getElementById("graph-results");
    var errEl = document.getElementById("graph-error");
    if (errEl) errEl.classList.add("hidden");
    if (!out) return;
    out.innerHTML = '<p class="text-slate-500 py-4">Running query…</p>';
    try {
      var body = buildGraphPayload();
      const data = await apiFetch("/graph", {
        method: "POST",
        body: JSON.stringify(body),
      });
      out.innerHTML =
        '<pre class="kb-json overflow-x-auto rounded-lg border border-slate-700 bg-slate-950/80 p-4 text-slate-300">' +
        escapeHtml(JSON.stringify(data, null, 2)) +
        "</pre>";
    } catch (e) {
      out.innerHTML = "";
      if (errEl) {
        errEl.textContent = e.message || "Graph query failed";
        errEl.classList.remove("hidden");
      }
    }
  }

  async function runIndex() {
    var mode =
      (document.querySelector('input[name="index-mode"]:checked') || {}).value || "full";
    var directory = document.getElementById("idx-directory")
      ? document.getElementById("idx-directory").value.trim()
      : "";
    var base_ref = document.getElementById("idx-base-ref")
      ? document.getElementById("idx-base-ref").value.trim()
      : "HEAD~1";
    var head_ref = document.getElementById("idx-head-ref")
      ? document.getElementById("idx-head-ref").value.trim()
      : "HEAD";
    var repository = document.getElementById("idx-repository")
      ? document.getElementById("idx-repository").value.trim()
      : "";
    var statusEl = document.getElementById("index-status");
    var errEl = document.getElementById("index-error");
    if (errEl) errEl.classList.add("hidden");
    if (!directory) {
      if (errEl) {
        errEl.textContent = "Directory path is required.";
        errEl.classList.remove("hidden");
      }
      return;
    }
    var body = { directory: directory, mode: mode };
    if (mode === "incremental") {
      body.base_ref = base_ref;
      body.head_ref = head_ref;
    }
    if (repository) body.repository = repository;
    if (statusEl) {
      statusEl.textContent = "Indexing…";
      statusEl.classList.remove("hidden", "text-emerald-400", "text-red-400", "text-sky-400");
      statusEl.classList.add("text-sky-400");
    }
    try {
      const data = await apiFetch("/index", {
        method: "POST",
        body: JSON.stringify(body),
      });
      if (statusEl) {
        statusEl.classList.remove("text-sky-400");
        statusEl.classList.add("text-emerald-400");
        statusEl.textContent = JSON.stringify(data.stats != null ? data.stats : data, null, 2).slice(0, 1200);
      }
    } catch (e) {
      if (statusEl) statusEl.textContent = "";
      if (errEl) {
        errEl.textContent = e.message || "Index failed";
        errEl.classList.remove("hidden");
      }
    }
  }

  function updateIndexModeUi() {
    var mode =
      (document.querySelector('input[name="index-mode"]:checked') || {}).value || "full";
    var inc = document.getElementById("idx-incremental-fields");
    if (inc) inc.classList.toggle("hidden", mode !== "incremental");
  }

  function escapeHtml(s) {
    var d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function escapeAttr(s) {
    return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  }

  function init() {
    var tokenInput = document.getElementById("api-token-input");
    var tokenToggle = document.getElementById("token-toggle");
    var tokenSave = document.getElementById("token-save");
    if (tokenInput) tokenInput.value = getToken();
    if (tokenToggle && tokenInput) {
      tokenToggle.addEventListener("click", function () {
        tokenInput.classList.toggle("hidden");
        tokenInput.classList.toggle("w-48");
        if (!tokenInput.classList.contains("hidden")) tokenInput.focus();
      });
    }
    if (tokenSave && tokenInput) {
      tokenSave.addEventListener("click", function () {
        setToken(tokenInput.value.trim());
        checkHealth();
        loadOverview();
      });
    }

    document.querySelectorAll(".nav-item[data-page]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        showPage(btn.getAttribute("data-page"));
      });
    });

    document.getElementById("btn-search") &&
      document.getElementById("btn-search").addEventListener("click", runSearch);
    var sq = document.getElementById("search-query");
    if (sq) {
      sq.addEventListener("keydown", function (e) {
        if (e.key === "Enter") runSearch();
      });
    }

    var gqt = document.getElementById("graph-query-type");
    if (gqt) gqt.addEventListener("change", updateGraphFormFields);
    document.getElementById("btn-graph-run") &&
      document.getElementById("btn-graph-run").addEventListener("click", runGraphQuery);
    updateGraphFormFields();

    document.querySelectorAll('input[name="index-mode"]').forEach(function (r) {
      r.addEventListener("change", updateIndexModeUi);
    });
    updateIndexModeUi();
    document.getElementById("btn-index") &&
      document.getElementById("btn-index").addEventListener("click", runIndex);

    var toggle = document.getElementById("sidebar-toggle");
    var aside = document.getElementById("sidebar-nav");
    if (toggle && aside) {
      toggle.addEventListener("click", function () {
        if (!window.matchMedia("(max-width: 1023px)").matches) return;
        var visible = !aside.classList.contains("hidden");
        if (visible) {
          aside.classList.add("hidden");
          aside.classList.remove("flex", "flex-col");
          toggle.setAttribute("aria-expanded", "false");
        } else {
          aside.classList.remove("hidden");
          aside.classList.add("flex", "flex-col");
          toggle.setAttribute("aria-expanded", "true");
        }
      });
    }

    showPage("overview");
    checkHealth();
    setInterval(checkHealth, 60000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
