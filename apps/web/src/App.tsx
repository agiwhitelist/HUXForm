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
  canNew: boolean;
}) {
  return (
    <div className="corner">
      <button className="corner-btn" onClick={props.onHistory}>
        Sessions <span className="kbd">\</span>
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
  return (
    <div className="approval-overlay">
      <div className="approval-card">
        <div className="approval-h">Approval required</div>
        <div className="approval-label">{req.label}</div>
        {req.details ? (
          <pre className="approval-details">
            {JSON.stringify(req.details, null, 2)}
          </pre>
        ) : null}
        <div className="approval-actions">
          <button onClick={() => props.onResolve(req, false)}>Deny</button>
          <button className="primary" onClick={() => props.onResolve(req, true)}>
            Approve
          </button>
        </div>
      </div>
    </div>
  );
}


/* -------------------------------------------------------------------- */
/* Utilities                                                             */
/* -------------------------------------------------------------------- */

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
