import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ApprovalRequest, Bridge, TaskEvent } from "./bridge";

type TaskPlan = {
  task_type: string;
  presentation_mode: string;
  visual_concept: string;
  rationale: string;
  steps: string[];
  tool_hints: string[];
  needs_user_input: boolean;
};

type TaskSnapshot = {
  id: string;
  goal: string;
  status: string;
  plan: TaskPlan | null;
  state: Record<string, unknown>;
  final_result: unknown;
  error: string | null;
  has_ui: boolean;
};

type Tool = {
  name: string;
  title: string;
  description: string;
  risk: string;
  requires_approval: boolean;
  params: Record<string, unknown>;
};

const EXAMPLES = [
  "Проверь этот CSV на дубли (я его сейчас загружу).",
  "Найди 10 Instagram-блогеров для рекламы FasonAI, бюджет 5-10к ₽.",
  "Подготовь маркетинговый аудит лендинга example.com.",
  "Сравни 3 платёжные системы для SaaS из РФ.",
  "Объясни, что такое MCP, в трёх абзацах.",
];

export function App() {
  const [goal, setGoal] = useState("");
  const [taskId, setTaskId] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<TaskSnapshot | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [iframeReady, setIframeReady] = useState(false);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const bridgeRef = useRef<Bridge | null>(null);
  const reloadTimer = useRef<number | null>(null);

  // Fetch tool list once for the boot payload
  useEffect(() => {
    fetch("/api/tools")
      .then((r) => r.json())
      .then((d) => setTools(d.tools || []))
      .catch(() => setTools([]));
  }, []);

  // Poll snapshot until UI is ready, then stop
  useEffect(() => {
    if (!taskId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await fetch(`/api/tasks/${taskId}`);
        const d: TaskSnapshot = await r.json();
        if (cancelled) return;
        setSnapshot(d);
        if (d.has_ui && !iframeReady) {
          // Force the iframe to load now that HTML is available
          const f = iframeRef.current;
          if (f) f.src = `/api/tasks/${taskId}/ui?t=${Date.now()}`;
          setIframeReady(true);
        }
      } catch {
        // ignore
      }
    };
    tick();
    const handle = window.setInterval(tick, 1200);
    return () => {
      cancelled = true;
      clearInterval(handle);
    };
  }, [taskId, iframeReady]);

  // Set up bridge when iframe is rendered
  useEffect(() => {
    if (!taskId) return;
    const iframe = iframeRef.current;
    if (!iframe) return;
    const bridge = new Bridge({
      iframe,
      taskId,
      onEvent: (ev) => {
        setEvents((prev) => {
          const next = prev.concat(ev);
          return next.length > 400 ? next.slice(-400) : next;
        });
      },
      onApprovalRequest: (req) => {
        setApprovals((prev) => prev.concat(req));
      },
    });
    bridge.attachEventStream();
    bridgeRef.current = bridge;
    return () => {
      bridge.destroy();
      bridgeRef.current = null;
    };
  }, [taskId]);

  // Re-send boot payload whenever the plan/tools change (so the iframe boots correctly after reload)
  useEffect(() => {
    if (!bridgeRef.current || !snapshot?.plan) return;
    bridgeRef.current.setBootPayload({
      plan: snapshot.plan,
      tools,
      goal: snapshot.goal,
    });
  }, [snapshot?.plan, tools, snapshot?.goal]);

  const onSubmit = useCallback(async () => {
    const text = goal.trim();
    if (!text || submitting) return;
    setSubmitting(true);
    setError(null);
    setEvents([]);
    setApprovals([]);
    setIframeReady(false);
    setSnapshot(null);
    setTaskId(null);
    try {
      const r = await fetch("/api/tasks", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ goal: text }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setTaskId(d.task_id);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setSubmitting(false);
    }
  }, [goal, submitting]);

  const reset = useCallback(() => {
    if (reloadTimer.current) window.clearTimeout(reloadTimer.current);
    setTaskId(null);
    setSnapshot(null);
    setEvents([]);
    setApprovals([]);
    setIframeReady(false);
    setError(null);
  }, []);

  const resolveApproval = useCallback((req: ApprovalRequest, ok: boolean) => {
    setApprovals((prev) => prev.filter((a) => a.id !== req.id));
    if (req.source === "backend" && req.approvalId) {
      bridgeRef.current?.resolveBackendApproval(req.approvalId, ok);
    } else {
      bridgeRef.current?.resolveIframeApproval(req.id, ok);
    }
  }, []);

  const status = snapshot?.status ?? (taskId ? "starting" : "idle");
  const plan = snapshot?.plan ?? null;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="dot" />
          <span className="brand-name">AGUI</span>
          <span className="brand-sub">generative human-experience runtime</span>
        </div>
        {taskId && (
          <button className="ghost" onClick={reset}>
            New task
          </button>
        )}
      </header>

      {!taskId && (
        <Landing
          goal={goal}
          setGoal={setGoal}
          onSubmit={onSubmit}
          submitting={submitting}
          error={error}
        />
      )}

      {taskId && (
        <main className="workspace">
          <aside className="sidebar">
            <PlanPanel status={status} plan={plan} snapshot={snapshot} />
            <EventsPanel events={events} />
          </aside>
          <section className="stage">
            <iframe
              ref={iframeRef}
              className="stage-frame"
              title="AGUI experience"
              sandbox="allow-scripts allow-forms allow-pointer-lock allow-popups"
              src="about:blank"
            />
          </section>
        </main>
      )}

      {approvals.length > 0 && (
        <ApprovalOverlay
          requests={approvals}
          onResolve={resolveApproval}
        />
      )}
    </div>
  );
}

function Landing(props: {
  goal: string;
  setGoal: (v: string) => void;
  onSubmit: () => void;
  submitting: boolean;
  error: string | null;
}) {
  return (
    <div className="landing">
      <div className="landing-inner">
        <h1>Опиши задачу — AGUI придумает интерфейс под неё.</h1>
        <p className="lede">
          Не чат. Не дашборд-конструктор. Каждый раз — мини-приложение,
          сгенерированное под конкретную задачу, в безопасном sandbox.
        </p>
        <textarea
          autoFocus
          value={props.goal}
          onChange={(e) => props.setGoal(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") props.onSubmit();
          }}
          placeholder="Например: проверь этот CSV на дубли, или подбери блогеров для FasonAI…"
          rows={5}
        />
        <div className="landing-actions">
          <button
            className="primary"
            disabled={!props.goal.trim() || props.submitting}
            onClick={props.onSubmit}
          >
            {props.submitting ? "Запускаю…" : "Generate experience  ⌘↵"}
          </button>
          {props.error && <span className="err">{props.error}</span>}
        </div>
        <div className="examples">
          {EXAMPLES.map((e) => (
            <button key={e} className="chip" onClick={() => props.setGoal(e)}>
              {e}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function PlanPanel({
  status,
  plan,
  snapshot,
}: {
  status: string;
  plan: TaskPlan | null;
  snapshot: TaskSnapshot | null;
}) {
  return (
    <div className="panel">
      <div className="panel-h">
        <span className="status-pill" data-status={status}>
          {status}
        </span>
        {plan && <span className="mode">{plan.presentation_mode}</span>}
      </div>
      {snapshot && <div className="goal">{snapshot.goal}</div>}
      {plan ? (
        <>
          <div className="concept">{plan.visual_concept}</div>
          <div className="rationale">{plan.rationale}</div>
          <ol className="steps">
            {plan.steps.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
          {plan.tool_hints?.length > 0 && (
            <div className="hints">
              {plan.tool_hints.map((t) => (
                <span key={t} className="tag">
                  {t}
                </span>
              ))}
            </div>
          )}
        </>
      ) : (
        <div className="dim">Planning…</div>
      )}
    </div>
  );
}

function EventsPanel({ events }: { events: TaskEvent[] }) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [events.length]);

  const filtered = useMemo(
    () => events.filter((e) => e.type !== "heartbeat"),
    [events],
  );
  return (
    <div className="panel events">
      <div className="panel-h">
        <span className="panel-title">events</span>
        <span className="count">{filtered.length}</span>
      </div>
      <div className="events-list" ref={ref}>
        {filtered.map((ev, i) => (
          <EventRow key={i} ev={ev} />
        ))}
        {filtered.length === 0 && <div className="dim">No events yet.</div>}
      </div>
    </div>
  );
}

function EventRow({ ev }: { ev: TaskEvent }) {
  const type = String(ev.type);
  let label = type;
  let extra: string | null = null;
  if (type === "tool_called") {
    label = `→ ${ev.tool}`;
    extra = ev.risk ? String(ev.risk) : null;
  } else if (type === "tool_result") {
    label = `✓ ${ev.tool}`;
  } else if (type === "tool_error") {
    label = `✗ ${ev.tool}`;
    extra = String(ev.message ?? "");
  } else if (type === "log") {
    label = `· ${ev.message}`;
    extra = String(ev.level ?? "");
  } else if (type === "plan_ready") {
    label = "plan ready";
  } else if (type === "ui_ready") {
    label = `ui ready (${ev.bytes}b)`;
  } else if (type === "state_patch") {
    label = "state patched";
  } else if (type === "final_result") {
    label = "final result";
  } else if (type === "approval_required") {
    label = `approval: ${ev.tool}`;
  } else if (type === "failed") {
    label = `failed: ${ev.message}`;
  }
  return (
    <div className={`ev ev-${type}`}>
      <span className="ev-label">{label}</span>
      {extra && <span className="ev-extra">{extra}</span>}
    </div>
  );
}

function ApprovalOverlay({
  requests,
  onResolve,
}: {
  requests: ApprovalRequest[];
  onResolve: (req: ApprovalRequest, ok: boolean) => void;
}) {
  const req = requests[0];
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
          <button className="ghost" onClick={() => onResolve(req, false)}>
            Deny
          </button>
          <button className="primary" onClick={() => onResolve(req, true)}>
            Approve
          </button>
        </div>
      </div>
    </div>
  );
}
