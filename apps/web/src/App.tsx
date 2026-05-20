/* AGUI shell.
 *
 * Not a chat. The whole product is a single stage: a moment of stillness
 * (the prompt), then a generated interface that takes over the screen.
 *
 *   Landing      → one large prompt-slab. Press Enter / Cmd+Enter to begin.
 *   Stage        → top scribe ribbon + full-bleed iframe + optional follow-up.
 *   History      → fullscreen gallery of past sessions, summoned by `\` key.
 *   Inspector    → side drawer for telemetry, off by default.
 *
 * The generated iframe (window.agui) is the source of interaction. The
 * shell only narrates "what AGUI is doing" — it does not host the work.
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { api, FileRec, Thread, ThreadSummary, Turn as TurnSnap } from "./api";
import { ApprovalRequest, Bridge } from "./bridge";
import { useMic } from "./mic";
import { Stage } from "./Turn";

type Mode =
  | { kind: "landing" }
  | { kind: "session"; thread_id: string };

const HINTS = [
  "check this CSV for duplicates",
  "scout 10 Instagram creators for a $200 campaign",
  "explain what MCP is",
  "compare three payment processors for a SaaS",
  "audit the landing page at example.com",
  "deploy the project, then show me a health check",
  "draft a one-pager for the next investor meeting",
  "design a triage console for unresolved support tickets",
];

const HERO_VERBS = [
  "look like",
  "feel like",
  "behave",
  "respond",
  "remember",
  "answer",
];

export function App() {
  const [mode, setMode] = useState<Mode>({ kind: "landing" });
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [currentTurn, setCurrentTurn] = useState<TurnSnap | null>(null);
  const [tools, setTools] = useState<
    Array<{ name: string; title: string; description: string; risk: string; source: string; requires_approval: boolean }>
  >([]);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [planSwatches, setPlanSwatches] = useState<Record<string, string[]>>({});
  const bridgesByTurn = useRef<Map<string, Bridge>>(new Map());

  const registerBridge = useCallback((id: string, bridge: Bridge | null) => {
    if (bridge) bridgesByTurn.current.set(id, bridge);
    else bridgesByTurn.current.delete(id);
  }, []);

  // load tool registry once
  useEffect(() => {
    api.tools().then((d) => setTools(d.tools as any)).catch(() => {});
  }, []);

  // load thread list, refresh periodically
  const refreshThreads = useCallback(async () => {
    try {
      const d = await api.listThreads();
      setThreads(d.threads);
    } catch {}
  }, []);
  useEffect(() => {
    refreshThreads();
    const h = window.setInterval(refreshThreads, 8000);
    return () => clearInterval(h);
  }, [refreshThreads]);

  // when entering a session, load its latest turn
  useEffect(() => {
    if (mode.kind !== "session") {
      setCurrentTurn(null);
      return;
    }
    let cancelled = false;
    api
      .getThread(mode.thread_id)
      .then((t: Thread) => {
        if (cancelled) return;
        const last = t.turns[t.turns.length - 1];
        if (last) setCurrentTurn(last);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [mode]);

  // hotkeys: \ opens history, Esc closes overlays, ⌘. toggles inspector
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "\\" && !isTyping(e.target)) {
        e.preventDefault();
        setHistoryOpen((v) => !v);
      } else if (e.key === "Escape") {
        if (historyOpen) setHistoryOpen(false);
        else if (inspectorOpen) setInspectorOpen(false);
      } else if ((e.metaKey || e.ctrlKey) && e.key === ".") {
        e.preventDefault();
        setInspectorOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [historyOpen, inspectorOpen]);

  const onApprovalRequest = useCallback((req: ApprovalRequest) => {
    setApprovals((prev) => {
      if (prev.find((p) => p.id === req.id && p.turnId === req.turnId)) return prev;
      return prev.concat(req);
    });
  }, []);

  const resolveApproval = useCallback(
    (req: ApprovalRequest, ok: boolean) => {
      setApprovals((prev) =>
        prev.filter((a) => !(a.id === req.id && a.turnId === req.turnId)),
      );
      if (req.source === "backend" && req.approvalId) {
        api.approve(req.turnId, req.approvalId, ok).catch(() => {});
      } else {
        bridgesByTurn.current.get(req.turnId)?.resolveIframeApproval(req.id, ok);
      }
    },
    [],
  );

  const onTurnUpdated = useCallback((t: TurnSnap) => {
    setCurrentTurn(t);
    // memoize palette per thread for the history covers
    const palette = t.plan?.visual_brief?.palette as Record<string, string> | undefined;
    if (t.thread_id && palette) {
      const cols = Object.values(palette).filter(Boolean).slice(0, 6);
      if (cols.length) setPlanSwatches((p) => ({ ...p, [t.thread_id]: cols as string[] }));
    }
  }, []);

  const startSession = useCallback(
    async (goal: string, fileIds: string[]) => {
      const res = await api.createThread(goal, fileIds, true);
      setMode({ kind: "session", thread_id: res.thread_id });
      try {
        const t = await api.getTurn(res.turn_id);
        setCurrentTurn(t);
      } catch {}
      refreshThreads();
    },
    [refreshThreads],
  );

  const followUp = useCallback(
    async (goal: string, fileIds: string[]) => {
      if (mode.kind !== "session") return;
      const last = currentTurn;
      const res = await api.addTurn(mode.thread_id, goal, fileIds, true, last?.id ?? null);
      try {
        const t = await api.getTurn(res.turn_id);
        setCurrentTurn(t);
      } catch {}
    },
    [mode, currentTurn],
  );

  const pickThread = useCallback((id: string) => {
    setHistoryOpen(false);
    setMode({ kind: "session", thread_id: id });
  }, []);

  const newSession = useCallback(() => {
    setHistoryOpen(false);
    setMode({ kind: "landing" });
    setCurrentTurn(null);
  }, []);

  const onStage = mode.kind === "session" && currentTurn != null;
  const [idle, setIdle] = useState(false);

  // mouse-idle detection (only matters on stage)
  useEffect(() => {
    if (!onStage) {
      setIdle(false);
      return;
    }
    let t: number | undefined;
    const wake = () => {
      setIdle(false);
      if (t) window.clearTimeout(t);
      t = window.setTimeout(() => setIdle(true), 3500);
    };
    wake();
    window.addEventListener("mousemove", wake);
    window.addEventListener("keydown", wake);
    return () => {
      window.removeEventListener("mousemove", wake);
      window.removeEventListener("keydown", wake);
      if (t) window.clearTimeout(t);
    };
  }, [onStage]);

  // palette sync: paint shell with active visual_brief
  useEffect(() => {
    const root = document.documentElement;
    const palette = currentTurn?.plan?.visual_brief?.palette as Record<string, string> | undefined;
    if (palette) {
      const bg = palette.bg || palette.background || "";
      const ink = palette.ink || palette.fg || "";
      const accent = palette.accent || "";
      if (bg) root.style.setProperty("--task-bg", bg);
      else root.style.removeProperty("--task-bg");
      if (ink) root.style.setProperty("--task-ink", ink);
      else root.style.removeProperty("--task-ink");
      if (accent) root.style.setProperty("--task-accent", accent);
      else root.style.removeProperty("--task-accent");
    } else {
      root.style.removeProperty("--task-bg");
      root.style.removeProperty("--task-ink");
      root.style.removeProperty("--task-accent");
    }
  }, [currentTurn?.id, currentTurn?.plan?.visual_brief]);

  return (
    <div
      className={`app ${onStage ? "stage" : ""} ${onStage && idle ? "idle" : ""}`}
      onMouseMove={() => {
        if (idle) setIdle(false);
      }}
    >
      <Sigil />
      <Corner
        onHistory={() => setHistoryOpen(true)}
        onNew={newSession}
        onSettings={() => setSettingsOpen(true)}
        canNew={mode.kind === "session"}
      />

      {mode.kind === "landing" && <Landing onSubmit={startSession} />}

      {mode.kind === "session" && currentTurn && (
        <Stage
          turn={currentTurn}
          tools={tools}
          inspectorOpen={inspectorOpen}
          onToggleInspector={() => setInspectorOpen((v) => !v)}
          onApprovalRequest={onApprovalRequest}
          onTurnUpdated={onTurnUpdated}
          onFollowUp={followUp}
          registerBridge={registerBridge}
        />
      )}

      {historyOpen && (
        <History
          threads={threads}
          currentThreadId={mode.kind === "session" ? mode.thread_id : null}
          swatches={planSwatches}
          onPick={pickThread}
          onNew={newSession}
          onClose={() => setHistoryOpen(false)}
        />
      )}

      {approvals.length > 0 && (
        <ApprovalOverlay requests={approvals} onResolve={resolveApproval} />
      )}

      {settingsOpen && (
        <SettingsPanel onClose={() => setSettingsOpen(false)} />
      )}
    </div>
  );
}


/* -------------------------------------------------------------------- */
/* Corner chrome                                                         */
/* -------------------------------------------------------------------- */

function Sigil() {
  return (
    <div className="sigil">
      <div className="sigil-mark" />
      <span className="sigil-name">
        <b>HUXForm</b> — the interface takes the shape of the task
      </span>
    </div>
  );
}

function Corner(props: {
  onHistory: () => void;
  onNew: () => void;
  onSettings: () => void;
  canNew: boolean;
}) {
  return (
    <div className="corner">
      <button className="corner-btn" onClick={props.onHistory}>
        Sessions <span className="kbd">\</span>
      </button>
      <button className="corner-btn" onClick={props.onSettings}>
        Settings
      </button>
      {props.canNew && (
        <button className="corner-btn" onClick={props.onNew}>
          New
        </button>
      )}
    </div>
  );
}


/* -------------------------------------------------------------------- */
/* Landing                                                               */
/* -------------------------------------------------------------------- */

function Landing(props: {
  onSubmit: (goal: string, fileIds: string[]) => Promise<void>;
}) {
  const [goal, setGoal] = useState("");
  const [files, setFiles] = useState<FileRec[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [hintIdx, setHintIdx] = useState(() => Math.floor(Math.random() * HINTS.length));
  const [verbIdx, setVerbIdx] = useState(0);
  const mic = useMic({
    onTranscript: (t) => { if (t) setGoal((g) => (g ? g + " " : "") + t); },
    onError: (m) => setErr(m),
  });

  useEffect(() => {
    const h = window.setInterval(() => {
      setHintIdx((i) => (i + 1) % HINTS.length);
    }, 5200);
    return () => clearInterval(h);
  }, []);

  useEffect(() => {
    const h = window.setInterval(() => {
      setVerbIdx((i) => (i + 1) % HERO_VERBS.length);
    }, 2800);
    return () => clearInterval(h);
  }, []);

  const onPickFiles = async (list: FileList | null) => {
    if (!list) return;
    setErr(null);
    for (const f of Array.from(list)) {
      try {
        const rec = await api.uploadFile(f);
        setFiles((prev) => prev.concat(rec));
      } catch (e: any) {
        setErr(e?.message ?? String(e));
      }
    }
  };

  const onSubmit = async () => {
    const text = goal.trim();
    if (!text || busy) return;
    setBusy(true);
    setErr(null);
    try {
      await props.onSubmit(text, files.map((f) => f.id));
    } catch (e: any) {
      setErr(e?.message ?? String(e));
      setBusy(false);
    }
  };

  return (
    <section className="landing">
      <div className="landing-inner">
        <div className="landing-eyebrow">
          <span>Generative human-experience runtime</span>
        </div>

        <h1 className="landing-h">
          What should the&nbsp;
          <em>interface</em>
          &nbsp;
          <span key={verbIdx} className="hero-verb">
            {HERO_VERBS[verbIdx]}
          </span>
          &nbsp;today?
        </h1>

        <p className="landing-sub">
          Describe a task in one line. HUXForm designs a one-off mini-app for it —
          its own metaphor, palette, tempo. Not a chat. Not a dashboard kit.
          One interface, one task.
        </p>

        <div className="prompt-slab">
          <textarea
            autoFocus
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !busy) {
                e.preventDefault();
                onSubmit();
              }
            }}
            placeholder="A task. Any shape, any domain."
            rows={2}
          />

          <div className="prompt-meta">
            <label className="prompt-attach">
              <input
                type="file"
                multiple
                onChange={(e) => {
                  onPickFiles(e.currentTarget.files);
                  e.currentTarget.value = "";
                }}
              />
              {files.length === 0 ? "Attach" : `Attach · ${files.length}`}
            </label>

            {files.length > 0 && (
              <div className="prompt-attach-list">
                {files.map((f) => (
                  <span key={f.id} className="attached-pill">
                    <span>{f.name}</span>
                    <button
                      onClick={() =>
                        setFiles((prev) => prev.filter((x) => x.id !== f.id))
                      }
                      aria-label="remove"
                    >×</button>
                  </span>
                ))}
              </div>
            )}

            <span className="prompt-spacer" />

            {mic.available && (
              <button
                className={`prompt-mic mic-${mic.state}`}
                onClick={() => mic.toggle()}
                title={mic.state === "recording" ? "stop & transcribe" : "voice in"}
                type="button"
              >
                {micLabel(mic.state)}
              </button>
            )}

            <button
              className="prompt-key"
              disabled={!goal.trim() || busy}
              onClick={onSubmit}
            >
              {busy ? "summoning" : <>begin <b>↵</b></>}
            </button>
          </div>
        </div>

        <div className="landing-cue">
          try <em>{HINTS[hintIdx]}</em>
        </div>

        {err && <div className="landing-err">{err}</div>}
      </div>
    </section>
  );
}


/* -------------------------------------------------------------------- */
/* History overlay                                                       */
/* -------------------------------------------------------------------- */

function History(props: {
  threads: ThreadSummary[];
  currentThreadId: string | null;
  swatches: Record<string, string[]>;
  onPick: (id: string) => void;
  onNew: () => void;
  onClose: () => void;
}) {
  return (
    <div className="history" onClick={props.onClose}>
      <div className="history-h" onClick={(e) => e.stopPropagation()}>
        <h2>Past sessions</h2>
        <div style={{ display: "flex", gap: 14, alignItems: "baseline" }}>
          <button className="corner-btn" onClick={props.onNew}>
            New session
          </button>
          <span className="esc">esc · close</span>
        </div>
      </div>
      <div className="history-grid" onClick={(e) => e.stopPropagation()}>
        {props.threads.length === 0 && (
          <div className="history-empty">No sessions yet.</div>
        )}
        {props.threads.map((t) => {
          const cols = props.swatches[t.id] || defaultSwatch();
          return (
            <button
              key={t.id}
              className={`session-card ${
                t.id === props.currentThreadId ? "current" : ""
              }`}
              onClick={() => props.onPick(t.id)}
            >
              <div className="swatches">
                {cols.slice(0, 6).map((c, i) => (
                  <span key={i} style={{ background: c }} />
                ))}
              </div>
              <div className="session-card-title">{t.title || "untitled"}</div>
              <div className="session-card-meta">
                <span>{t.turn_count} turn{t.turn_count === 1 ? "" : "s"}</span>
                <span>{fmtAgo(t.created_at)}</span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}


/* -------------------------------------------------------------------- */
/* Approval modal                                                        */
/* -------------------------------------------------------------------- */

function ApprovalOverlay(props: {
  requests: ApprovalRequest[];
  onResolve: (req: ApprovalRequest, ok: boolean) => void;
}) {
  const req = props.requests[0];
  const d = (req.details as Record<string, unknown> | null) || null;
  const tool = (d?.tool as string) || "";
  const risk = (d?.risk as string) || "";
  const description = (d?.description as string) || "";
  const params = (d?.params_preview as Record<string, unknown>) || null;

  const isInstall = tool === "tools.install";
  const isUninstall = tool === "tools.uninstall";
  const isDestructive = risk === "destructive" || risk === "secret";
  const high = isInstall || isUninstall || isDestructive || risk === "filesystem";

  const trust = typeof params?.trust_score === "number" ? (params.trust_score as number) : null;
  const installCmd = isInstall && params
    ? `${(params.command as string) || ""} ${Array.isArray(params.args) ? (params.args as string[]).join(" ") : ""}`.trim()
    : "";
  const installAlias = (params?.alias as string) || "";
  const installSource = (params?.source_url as string) || "";
  const installDescription = (params?.description as string) || "";

  return (
    <div className="approval-overlay">
      <div className={`approval-card ${high ? "is-high-risk" : ""}`}>
        <div className="approval-h">
          <span className={`approval-pill ${high ? "high" : "low"}`}>
            {isInstall ? "install · approval required"
              : isUninstall ? "uninstall · approval required"
              : isDestructive ? "destructive · approval required"
              : risk
                ? `${risk} · approval required`
                : "approval required"}
          </span>
        </div>

        <div className="approval-label">
          {isInstall ? `Install MCP server "${installAlias || tool}"`
            : isUninstall ? `Uninstall MCP server "${installAlias || tool}"`
            : req.label}
        </div>

        {description && !isInstall ? (
          <p className="approval-desc">{description}</p>
        ) : null}

        {isInstall ? (
          <div className="approval-install">
            <div className="approval-field">
              <div className="approval-field-k">command</div>
              <code className="approval-field-v approval-cmd">{installCmd || "(none)"}</code>
            </div>
            {trust != null ? (
              <div className="approval-field">
                <div className="approval-field-k">trust score</div>
                <div className="approval-field-v">
                  <span className={`approval-trust ${trust >= 0.7 ? "good" : trust >= 0.45 ? "ok" : "low"}`}>
                    {trust.toFixed(2)}
                  </span>
                  <span className="approval-trust-note">
                    {trust >= 0.7 ? "official or widely trusted"
                      : trust >= 0.45 ? "community — review the source"
                      : "low signal — read the README before approving"}
                  </span>
                </div>
              </div>
            ) : null}
            {installSource ? (
              <div className="approval-field">
                <div className="approval-field-k">source</div>
                <a className="approval-field-v approval-link" href={installSource} target="_blank" rel="noopener noreferrer">{installSource}</a>
              </div>
            ) : null}
            {installDescription ? (
              <div className="approval-field">
                <div className="approval-field-k">summary</div>
                <div className="approval-field-v">{installDescription}</div>
              </div>
            ) : null}
            <p className="approval-warn">
              This spawns a subprocess and registers every tool the server advertises.
              Only approve sources you trust.
            </p>
          </div>
        ) : params && Object.keys(params).length ? (
          <pre className="approval-details">{JSON.stringify(params, null, 2)}</pre>
        ) : req.details ? (
          <pre className="approval-details">{JSON.stringify(req.details, null, 2)}</pre>
        ) : null}

        <div className="approval-actions">
          <button onClick={() => props.onResolve(req, false)}>Deny</button>
          <button
            className={`primary ${high ? "danger" : ""}`}
            onClick={() => props.onResolve(req, true)}
          >
            {isInstall ? "Install" : isUninstall ? "Uninstall" : "Approve"}
          </button>
        </div>
      </div>
    </div>
  );
}


/* -------------------------------------------------------------------- */
/* Settings panel — capability registry, cost dashboard, presets         */
/* -------------------------------------------------------------------- */

type Capabilities = Awaited<ReturnType<typeof api.capabilities>>;
type AuditStats = Awaited<ReturnType<typeof api.auditStats>>;
type Presets = Awaited<ReturnType<typeof api.presets>>;

function SettingsPanel(props: { onClose: () => void }) {
  const [tab, setTab] = useState<"caps" | "cost" | "presets">("caps");
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [stats, setStats] = useState<AuditStats | null>(null);
  const [presets, setPresets] = useState<Presets | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [working, setWorking] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setErr(null);
    try {
      const [c, s, p] = await Promise.all([
        api.capabilities(),
        api.auditStats(),
        api.presets(),
      ]);
      setCaps(c);
      setStats(s);
      setPresets(p);
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // close on Esc
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") props.onClose();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [props.onClose]);

  const uninstall = useCallback(async (alias: string) => {
    if (!window.confirm(`Uninstall MCP server "${alias}"?`)) return;
    setWorking(alias);
    try {
      await api.uninstallCapability(alias);
      await refresh();
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setWorking(null);
    }
  }, [refresh]);

  const activate = useCallback(async (name: string) => {
    try {
      await api.activatePreset(name);
      await refresh();
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    }
  }, [refresh]);

  return (
    <div className="settings-overlay" onClick={props.onClose}>
      <div className="settings-panel" onClick={(e) => e.stopPropagation()}>
        <header className="settings-h">
          <h2>Settings</h2>
          <div className="settings-tabs">
            <button className={tab === "caps" ? "on" : ""} onClick={() => setTab("caps")}>
              Capabilities {caps ? `· ${caps.mcp.length}` : ""}
            </button>
            <button className={tab === "cost" ? "on" : ""} onClick={() => setTab("cost")}>
              Cost & latency
            </button>
            <button className={tab === "presets" ? "on" : ""} onClick={() => setTab("presets")}>
              Presets {presets ? `· active: ${presets.active}` : ""}
            </button>
            <span className="esc">esc · close</span>
          </div>
        </header>

        {err && <div className="settings-err">{err}</div>}

        <div className="settings-body">
          {tab === "caps" && caps && (
            <CapsTab caps={caps} working={working} onUninstall={uninstall} />
          )}
          {tab === "cost" && stats && (
            <CostTab stats={stats} />
          )}
          {tab === "presets" && presets && (
            <PresetsTab presets={presets} onActivate={activate} onRefresh={refresh} setErr={setErr} />
          )}
        </div>
      </div>
    </div>
  );
}

function CapsTab(props: {
  caps: Capabilities;
  working: string | null;
  onUninstall: (alias: string) => void;
}) {
  const { mcp, openapi } = props.caps;
  return (
    <div className="caps-tab">
      <h3>MCP servers</h3>
      {mcp.length === 0 && <p className="muted">No MCP servers installed via discovery yet. Use <code>tools.discover</code> from any generated UI to find one, then <code>tools.install</code> to spawn it.</p>}
      <table className="caps-table">
        {mcp.length > 0 && (
          <thead><tr><th>alias</th><th>command</th><th>trust</th><th>tools</th><th>state</th><th></th></tr></thead>
        )}
        <tbody>
          {mcp.map((m) => (
            <tr key={m.alias}>
              <td><b>{m.alias}</b></td>
              <td><code>{m.command} {m.args.join(" ")}</code></td>
              <td>{m.trust_score != null ? m.trust_score.toFixed(2) : "—"}</td>
              <td>{m.tools.length}</td>
              <td>{m.running ? <span className="pill-running">running</span> : <span className="pill-stopped">stopped</span>}</td>
              <td>
                <button
                  className="danger"
                  disabled={props.working === m.alias}
                  onClick={() => props.onUninstall(m.alias)}
                >
                  {props.working === m.alias ? "..." : "Uninstall"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>OpenAPI</h3>
      {openapi.length === 0 ? (
        <p className="muted">None registered. POST to <code>/api/tools/openapi</code> to add a spec.</p>
      ) : (
        <ul>
          {openapi.map((o) => (
            <li key={o.alias}>
              <b>{o.alias}</b> · <code>{o.spec_url}</code>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CostTab(props: { stats: AuditStats }) {
  const { tools, totals, usage } = props.stats;
  return (
    <div className="cost-tab">
      <div className="cost-totals">
        <div><span className="k">tool calls</span><span className="v">{totals.calls}</span></div>
        <div><span className="k">tool time</span><span className="v">{(totals.total_ms / 1000).toFixed(2)}s</span></div>
        <div><span className="k">turns</span><span className="v">{usage.turns}</span></div>
        <div><span className="k">input tok</span><span className="v">{usage.input_tokens.toLocaleString()}</span></div>
        <div><span className="k">output tok</span><span className="v">{usage.output_tokens.toLocaleString()}</span></div>
      </div>

      <table className="cost-table">
        <thead>
          <tr>
            <th>tool</th><th>calls</th><th>fail</th>
            <th>avg ms</th><th>p50</th><th>p95</th><th>last</th>
          </tr>
        </thead>
        <tbody>
          {tools.length === 0 && (
            <tr><td colSpan={7} className="muted">No tool calls yet. Start a session.</td></tr>
          )}
          {tools.map((t) => (
            <tr key={t.tool}>
              <td><code>{t.tool}</code></td>
              <td>{t.count}</td>
              <td className={t.fail > 0 ? "bad" : ""}>{t.fail}</td>
              <td>{t.avg_ms.toFixed(0)}</td>
              <td>{t.p50_ms.toFixed(0)}</td>
              <td>{t.p95_ms.toFixed(0)}</td>
              <td>{t.last_ms.toFixed(0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PresetsTab(props: {
  presets: Presets;
  onActivate: (name: string) => void;
  onRefresh: () => void;
  setErr: (s: string | null) => void;
}) {
  const names = Object.keys(props.presets.presets);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<{
    name: string;
    bg: string; ink: string; accent: string;
    display: string; body: string; mono: string;
    banned: string; notes: string;
  }>({
    name: "",
    bg: "", ink: "", accent: "",
    display: "", body: "", mono: "",
    banned: "", notes: "",
  });

  const startNew = () => {
    setEditing("__new__");
    setDraft({ name: "", bg: "", ink: "", accent: "", display: "", body: "", mono: "", banned: "", notes: "" });
  };

  const startEdit = (name: string) => {
    const p = props.presets.presets[name];
    setEditing(name);
    setDraft({
      name: p.name,
      bg: p.palette.bg || "",
      ink: p.palette.ink || "",
      accent: p.palette.accent || "",
      display: p.typography.display || "",
      body: p.typography.body || "",
      mono: p.typography.mono || "",
      banned: p.banned_extra.join("\n"),
      notes: p.notes,
    });
  };

  const save = async () => {
    if (!draft.name.trim()) return;
    try {
      await api.upsertPreset({
        name: draft.name.trim(),
        palette: pruneEmpty({ bg: draft.bg, ink: draft.ink, accent: draft.accent }),
        typography: pruneEmpty({ display: draft.display, body: draft.body, mono: draft.mono }),
        banned_extra: draft.banned.split("\n").map((s) => s.trim()).filter(Boolean),
        notes: draft.notes,
      });
      setEditing(null);
      await props.onRefresh();
    } catch (e: any) {
      props.setErr(e?.message ?? String(e));
    }
  };

  const remove = async (name: string) => {
    if (name === "default") return;
    if (!window.confirm(`Delete preset "${name}"?`)) return;
    try {
      await api.deletePreset(name);
      await props.onRefresh();
    } catch (e: any) {
      props.setErr(e?.message ?? String(e));
    }
  };

  return (
    <div className="presets-tab">
      <div className="presets-list">
        {names.map((n) => {
          const p = props.presets.presets[n];
          const swatches = [p.palette.bg, p.palette.ink, p.palette.accent].filter(Boolean);
          const active = props.presets.active === n;
          return (
            <div key={n} className={`preset-card ${active ? "is-active" : ""}`}>
              <div className="preset-h">
                <b>{n}</b>
                {active && <span className="preset-active">active</span>}
              </div>
              <div className="preset-swatch">
                {swatches.map((c, i) => <span key={i} style={{ background: c as string }} />)}
                {swatches.length === 0 && <span className="muted">no palette anchors</span>}
              </div>
              {p.notes && <p className="preset-notes">{p.notes}</p>}
              <div className="preset-actions">
                {!active && <button onClick={() => props.onActivate(n)}>Activate</button>}
                <button onClick={() => startEdit(n)}>Edit</button>
                {n !== "default" && <button className="danger" onClick={() => remove(n)}>Delete</button>}
              </div>
            </div>
          );
        })}
        <button className="preset-new" onClick={startNew}>+ new preset</button>
      </div>

      {editing && (
        <div className="preset-editor">
          <h3>{editing === "__new__" ? "New preset" : `Edit "${editing}"`}</h3>
          <label>name<input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} disabled={editing !== "__new__"} /></label>
          <div className="preset-row">
            <label>bg<input value={draft.bg} placeholder="#0b0d10" onChange={(e) => setDraft({ ...draft, bg: e.target.value })} /></label>
            <label>ink<input value={draft.ink} placeholder="#e7e9ee" onChange={(e) => setDraft({ ...draft, ink: e.target.value })} /></label>
            <label>accent<input value={draft.accent} placeholder="#7aa2ff" onChange={(e) => setDraft({ ...draft, accent: e.target.value })} /></label>
          </div>
          <div className="preset-row">
            <label>display font<input value={draft.display} placeholder="Inter" onChange={(e) => setDraft({ ...draft, display: e.target.value })} /></label>
            <label>body font<input value={draft.body} placeholder="Inter" onChange={(e) => setDraft({ ...draft, body: e.target.value })} /></label>
            <label>mono font<input value={draft.mono} placeholder="JetBrains Mono" onChange={(e) => setDraft({ ...draft, mono: e.target.value })} /></label>
          </div>
          <label>banned patterns (one per line)<textarea rows={3} value={draft.banned} onChange={(e) => setDraft({ ...draft, banned: e.target.value })} /></label>
          <label>house-style notes<textarea rows={3} value={draft.notes} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} /></label>
          <div className="preset-editor-actions">
            <button onClick={() => setEditing(null)}>Cancel</button>
            <button className="primary" onClick={save} disabled={!draft.name.trim()}>Save</button>
          </div>
        </div>
      )}
    </div>
  );
}

function pruneEmpty(obj: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(obj)) if (v && v.trim()) out[k] = v.trim();
  return out;
}


/* -------------------------------------------------------------------- */
/* Utilities                                                             */
/* -------------------------------------------------------------------- */

function micLabel(state: string): string {
  if (state === "recording") return "● stop";
  if (state === "asking") return "…";
  if (state === "transcribing") return "writing";
  return "🎙 voice";
}

function isTyping(target: EventTarget | null): boolean {
  if (!target || !(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    target.isContentEditable === true
  );
}

function defaultSwatch(): string[] {
  return ["#1a1d24", "#2a2d36", "#3a3d46", "#4a4d56", "#5a5d66", "#6a6d76"];
}

function fmtAgo(ts: number): string {
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}
