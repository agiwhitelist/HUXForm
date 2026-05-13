import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { api, FileRec, ThreadSummary, Turn as TurnSnap } from "./api";
import { ApprovalRequest, Bridge } from "./bridge";
import { TurnView } from "./Turn";

type Mode =
  | { kind: "landing" }
  | { kind: "thread"; thread_id: string };

const EXAMPLES = [
  "Проверь этот CSV на дубли (я его сейчас прикреплю).",
  "Найди 10 Instagram-блогеров для рекламы FasonAI, бюджет 5–10к ₽.",
  "Подготовь маркетинговый аудит лендинга example.com.",
  "Сравни 3 платёжные системы для российского SaaS.",
  "Объясни, что такое MCP, в трёх абзацах.",
];

export function App() {
  const [mode, setMode] = useState<Mode>({ kind: "landing" });
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [turns, setTurns] = useState<TurnSnap[]>([]);
  const [tools, setTools] = useState<
    Array<{ name: string; title: string; description: string; risk: string; source: string; requires_approval: boolean }>
  >([]);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const bridgesByTurn = useRef<Map<string, Bridge>>(new Map());

  const registerBridge = useCallback((id: string, bridge: Bridge | null) => {
    if (bridge) bridgesByTurn.current.set(id, bridge);
    else bridgesByTurn.current.delete(id);
  }, []);

  // Tools registry (display only)
  useEffect(() => {
    api.tools().then((d) => setTools(d.tools as any)).catch(() => {});
  }, []);

  // Threads list
  const refreshThreads = useCallback(async () => {
    try {
      const d = await api.listThreads();
      setThreads(d.threads);
    } catch {}
  }, []);
  useEffect(() => {
    refreshThreads();
  }, [refreshThreads]);

  // Load a thread's turns when entering it
  useEffect(() => {
    if (mode.kind !== "thread") return;
    let cancelled = false;
    api
      .getThread(mode.thread_id)
      .then((t) => {
        if (cancelled) return;
        setTurns(t.turns);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [mode]);

  // Periodically refresh threads list to update titles
  useEffect(() => {
    const h = window.setInterval(refreshThreads, 5000);
    return () => clearInterval(h);
  }, [refreshThreads]);

  const onTurnUpdated = useCallback((t: TurnSnap) => {
    setTurns((prev) => prev.map((x) => (x.id === t.id ? t : x)));
  }, []);

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

  const startFromLanding = useCallback(
    async (goal: string, fileIds: string[], autoProceed: boolean) => {
      const res = await api.createThread(goal, fileIds, autoProceed);
      setMode({ kind: "thread", thread_id: res.thread_id });
      // Optimistic: immediately fetch the new turn
      try {
        const t = await api.getTurn(res.turn_id);
        setTurns([t]);
      } catch {}
      refreshThreads();
    },
    [refreshThreads],
  );

  const addTurnToCurrent = useCallback(
    async (goal: string, fileIds: string[], autoProceed: boolean) => {
      if (mode.kind !== "thread") return;
      const last = turns[turns.length - 1];
      const res = await api.addTurn(
        mode.thread_id,
        goal,
        fileIds,
        autoProceed,
        last?.id ?? null,
      );
      try {
        const t = await api.getTurn(res.turn_id);
        setTurns((prev) => prev.concat(t));
      } catch {}
    },
    [mode, turns],
  );

  return (
    <div className="app">
      <TopBar
        threadId={mode.kind === "thread" ? mode.thread_id : null}
        threads={threads}
        onPick={(tid) => setMode({ kind: "thread", thread_id: tid })}
        onNewThread={() => {
          setMode({ kind: "landing" });
          setTurns([]);
        }}
      />

      {mode.kind === "landing" ? (
        <Landing onSubmit={startFromLanding} />
      ) : (
        <ThreadWorkspace
          turns={turns}
          tools={tools}
          onApprovalRequest={onApprovalRequest}
          onTurnUpdated={onTurnUpdated}
          onAddTurn={addTurnToCurrent}
          registerBridge={registerBridge}
        />
      )}

      {approvals.length > 0 && (
        <ApprovalOverlay requests={approvals} onResolve={resolveApproval} />
      )}
    </div>
  );
}


function TopBar(props: {
  threadId: string | null;
  threads: ThreadSummary[];
  onPick: (id: string) => void;
  onNewThread: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <header className="topbar">
      <div className="brand">
        <svg className="brand-mark" viewBox="0 0 64 64" aria-hidden="true">
          <defs>
            <linearGradient id="bm-1" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%"   stopColor="#7C5CFF"/>
              <stop offset="100%" stopColor="#FF8A5C"/>
            </linearGradient>
            <linearGradient id="bm-2" x1="0" y1="1" x2="1" y2="0">
              <stop offset="0%"   stopColor="#5BD2A2"/>
              <stop offset="100%" stopColor="#7C5CFF"/>
            </linearGradient>
          </defs>
          <circle cx="32" cy="32" r="26" stroke="url(#bm-2)" strokeWidth="2" strokeDasharray="4 3" opacity=".55" fill="none"/>
          <rect x="14" y="14" width="36" height="36" rx="9" stroke="url(#bm-1)" strokeWidth="2.4" fill="none"/>
          <path d="M 32 21 L 45 43 L 19 43 Z" stroke="#FF8A5C" strokeWidth="2.4" strokeLinejoin="round" fill="none"/>
        </svg>
        <span className="brand-name">Morphic</span>
        <span className="brand-sub">the interface takes the shape of the task</span>
      </div>
      <div className="top-right">
        <div className="threads-menu">
          <button className="ghost" onClick={() => setOpen((v) => !v)}>
            {props.threads.length > 0 ? `Threads · ${props.threads.length}` : "Threads"}
          </button>
          {open && (
            <div className="threads-popover" onMouseLeave={() => setOpen(false)}>
              {props.threads.length === 0 && (
                <div className="dim small">No threads yet.</div>
              )}
              {props.threads.map((t) => (
                <button
                  key={t.id}
                  className={`thread-row ${t.id === props.threadId ? "current" : ""}`}
                  onClick={() => {
                    setOpen(false);
                    props.onPick(t.id);
                  }}
                >
                  <span className="thread-title">{t.title || "(untitled)"}</span>
                  <span className="thread-meta">{t.turn_count} · {fmtAgo(t.created_at)}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        <button className="primary small" onClick={props.onNewThread}>
          New
        </button>
      </div>
    </header>
  );
}


function Landing(props: {
  onSubmit: (goal: string, fileIds: string[], autoProceed: boolean) => Promise<void>;
}) {
  const [goal, setGoal] = useState("");
  const [files, setFiles] = useState<FileRec[]>([]);
  const [autoProceed, setAutoProceed] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

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
      await props.onSubmit(text, files.map((f) => f.id), autoProceed);
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="landing">
      <div className="landing-inner">
        <h1>Опиши задачу — Morphic придумает интерфейс под неё.</h1>
        <p className="lede">
          Не чат. Не дашборд-конструктор. Каждый раз — уникальный мини-app
          под конкретную задачу, в безопасном sandbox. Можно прикрепить файлы.
        </p>

        <textarea
          autoFocus
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") onSubmit();
          }}
          placeholder="Например: проверь этот CSV на дубли, или подбери блогеров для FasonAI…"
          rows={5}
        />

        {files.length > 0 && (
          <div className="composer-files">
            {files.map((f) => (
              <span key={f.id} className="file-pill">
                <span className="file-name">{f.name}</span>
                <span className="file-size">{fmtBytes(f.size)}</span>
                <button
                  className="file-x"
                  onClick={() =>
                    setFiles((prev) => prev.filter((x) => x.id !== f.id))
                  }
                  aria-label="remove"
                >×</button>
              </span>
            ))}
          </div>
        )}

        <div className="landing-actions">
          <label className="ghost file-btn">
            <input
              type="file"
              multiple
              onChange={(e) => {
                onPickFiles(e.target.files);
                e.currentTarget.value = "";
              }}
            />
            Attach
          </label>

          <label className="check">
            <input
              type="checkbox"
              checked={autoProceed}
              onChange={(e) => setAutoProceed(e.target.checked)}
            />
            <span>Auto-proceed past plan</span>
          </label>

          <span className="spacer" />

          <button
            className="primary"
            disabled={!goal.trim() || busy}
            onClick={onSubmit}
          >
            {busy ? "Запускаю…" : "Generate experience  ⌘↵"}
          </button>
        </div>

        {err && <div className="err">{err}</div>}

        <div className="examples">
          {EXAMPLES.map((e) => (
            <button key={e} className="chip" onClick={() => setGoal(e)}>
              {e}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}


function ThreadWorkspace(props: {
  turns: TurnSnap[];
  tools: Array<{ name: string; title: string; description: string; risk: string; source: string; requires_approval: boolean }>;
  onApprovalRequest: (req: ApprovalRequest) => void;
  onTurnUpdated: (t: TurnSnap) => void;
  onAddTurn: (goal: string, fileIds: string[], autoProceed: boolean) => Promise<void>;
  registerBridge: (id: string, bridge: Bridge | null) => void;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [props.turns.length]);

  return (
    <main className="workspace">
      <div className="thread-scroll" ref={scrollRef}>
        {props.turns.map((t, i) => (
          <TurnView
            key={t.id}
            turn={t}
            isLast={i === props.turns.length - 1}
            tools={props.tools}
            onApprovalRequest={props.onApprovalRequest}
            onTurnUpdated={props.onTurnUpdated}
            registerBridge={props.registerBridge}
          />
        ))}
      </div>
      <Composer onSend={props.onAddTurn} />
    </main>
  );
}


function Composer(props: {
  onSend: (goal: string, fileIds: string[], autoProceed: boolean) => Promise<void>;
}) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<FileRec[]>([]);
  const [autoProceed, setAutoProceed] = useState(true);
  const [busy, setBusy] = useState(false);

  const onSend = async () => {
    if (!text.trim() || busy) return;
    setBusy(true);
    try {
      await props.onSend(text.trim(), files.map((f) => f.id), autoProceed);
      setText("");
      setFiles([]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="composer">
      <div className="composer-row">
        <label className="ghost file-btn small">
          <input
            type="file"
            multiple
            onChange={async (e) => {
              const list = e.currentTarget.files;
              e.currentTarget.value = "";
              if (!list) return;
              for (const f of Array.from(list)) {
                try {
                  const rec = await api.uploadFile(f);
                  setFiles((p) => p.concat(rec));
                } catch {}
              }
            }}
          />
          📎
        </label>
        <input
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") onSend();
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSend();
            }
          }}
          placeholder="Refine, add a follow-up, or start a related task…"
        />
        <label className="check small">
          <input
            type="checkbox"
            checked={autoProceed}
            onChange={(e) => setAutoProceed(e.target.checked)}
          />
          <span>auto</span>
        </label>
        <button
          className="primary small"
          disabled={!text.trim() || busy}
          onClick={onSend}
        >
          {busy ? "…" : "Send"}
        </button>
      </div>
      {files.length > 0 && (
        <div className="composer-files">
          {files.map((f) => (
            <span key={f.id} className="file-pill">
              <span className="file-name">{f.name}</span>
              <span className="file-size">{fmtBytes(f.size)}</span>
              <button
                className="file-x"
                onClick={() => setFiles((p) => p.filter((x) => x.id !== f.id))}
              >×</button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}


function ApprovalOverlay(props: {
  requests: ApprovalRequest[];
  onResolve: (req: ApprovalRequest, ok: boolean) => void;
}) {
  const req = props.requests[0];
  return (
    <div className="overlay">
      <div className="approval-card">
        <div className="approval-h">Approval required</div>
        <div className="approval-label">{req.label}</div>
        {req.details ? (
          <pre className="approval-details">
            {JSON.stringify(req.details, null, 2)}
          </pre>
        ) : null}
        <div className="approval-actions">
          <button className="ghost" onClick={() => props.onResolve(req, false)}>
            Deny
          </button>
          <button className="primary" onClick={() => props.onResolve(req, true)}>
            Approve
          </button>
        </div>
      </div>
    </div>
  );
}


function fmtAgo(ts: number): string {
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KB`;
  return `${(n / 1024 / 1024).toFixed(1)}MB`;
}
