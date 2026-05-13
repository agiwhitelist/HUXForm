import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { api, Turn as TurnSnap } from "./api";
import { ApprovalRequest, Bridge, TaskEvent } from "./bridge";

type Props = {
  turn: TurnSnap;
  isLast: boolean;
  tools: Array<{ name: string; title: string; description: string; risk: string; source: string }>;
  onApprovalRequest: (req: ApprovalRequest) => void;
  onTurnUpdated: (turn: TurnSnap) => void;
  registerBridge: (id: string, bridge: Bridge | null) => void;
};

export function TurnView({ turn: initial, isLast, tools, onApprovalRequest, onTurnUpdated, registerBridge }: Props) {
  const [turn, setTurn] = useState<TurnSnap>(initial);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [narrations, setNarrations] = useState<
    Array<{ text: string; tone: string; ts: number }>
  >([]);
  const [showInspector, setShowInspector] = useState(false);
  const [iframeLoaded, setIframeLoaded] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const bridgeRef = useRef<Bridge | null>(null);
  const onApprovalRef = useRef(onApprovalRequest);
  onApprovalRef.current = onApprovalRequest;

  // Replace local snapshot when parent provides a fresher one
  useEffect(() => {
    setTurn(initial);
  }, [initial.id, initial.status, initial.has_ui]);

  // Drive bridge + SSE; lasts for the lifetime of this Turn
  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    const bridge = new Bridge({
      iframe,
      turnId: turn.id,
      onEvent: (ev) => {
        setEvents((prev) => {
          const next = prev.concat(ev);
          return next.length > 600 ? next.slice(-600) : next;
        });
        if (ev.type === "narration") {
          setNarrations((prev) =>
            prev.concat({
              text: String(ev.text ?? ""),
              tone: String((ev as any).tone || "info"),
              ts: (ev.ts as number) || Date.now() / 1000,
            }),
          );
        }
        // Coalesce known transitions into snapshot state
        if (ev.type === "plan_ready" && ev.plan) {
          setTurn((p) => ({ ...p, plan: ev.plan as any, status: "awaiting_steer" }));
        } else if (ev.type === "awaiting_steer") {
          setTurn((p) => ({ ...p, status: "awaiting_steer" }));
        } else if (ev.type === "codegen_started") {
          setTurn((p) => ({ ...p, status: "generating" }));
        } else if (ev.type === "ui_ready") {
          setTurn((p) => ({ ...p, has_ui: true, status: "running" }));
        } else if (ev.type === "running") {
          setTurn((p) => ({ ...p, status: "running" }));
        } else if (ev.type === "final_result") {
          setTurn((p) => ({
            ...p,
            status: "done",
            final_result: (ev as any).result ?? null,
            answer_text: (ev as any).answer_only ? String(((ev as any).result || {}).answer || "") : p.answer_text,
          }));
        } else if (ev.type === "failed") {
          setTurn((p) => ({ ...p, status: "failed", error: String(ev.message ?? "") }));
        } else if (ev.type === "cancelled") {
          setTurn((p) => ({ ...p, status: "cancelled" }));
        }
      },
      onApprovalRequest: (req) => onApprovalRef.current(req),
    });
    bridge.attachEventStream();
    bridgeRef.current = bridge;
    registerBridge(turn.id, bridge);
    return () => {
      registerBridge(turn.id, null);
      bridge.destroy();
      bridgeRef.current = null;
    };
  }, [turn.id, registerBridge]);

  // Send boot payload to iframe once UI is ready
  useEffect(() => {
    if (!bridgeRef.current || !turn.plan) return;
    bridgeRef.current.setBootPayload({
      plan: turn.plan,
      tools,
      goal: turn.user_message,
      files: turn.files,
    });
  }, [turn.plan, tools, turn.user_message, turn.files]);

  // Once has_ui flips true, load the iframe src.
  useEffect(() => {
    if (!turn.has_ui) return;
    const f = iframeRef.current;
    if (!f) return;
    if (iframeLoaded) return;
    f.src = `/api/turns/${turn.id}/ui?t=${Date.now()}`;
    setIframeLoaded(true);
  }, [turn.has_ui, turn.id, iframeLoaded]);

  // Bubble snapshot back up for sidebar/history
  useEffect(() => {
    onTurnUpdated(turn);
  }, [turn, onTurnUpdated]);

  const onProceed = useCallback(async () => {
    try {
      await api.proceed(turn.id);
    } catch {}
  }, [turn.id]);

  const onCancel = useCallback(async () => {
    try {
      await api.cancel(turn.id);
    } catch {}
  }, [turn.id]);

  const plan = turn.plan;
  const brief = plan?.visual_brief || null;
  const status = turn.status;
  const isAnswerOnly = plan?.presentation_mode === "answer_only";
  const showStage = !isAnswerOnly && (status === "generating" || status === "running" || turn.has_ui);
  const eventsFiltered = useMemo(
    () => events.filter((e) => e.type !== "heartbeat"),
    [events],
  );

  return (
    <article className={`turn turn-${status}`}>
      <div className="turn-user">
        <span className="turn-user-tag">you</span>
        <div className="turn-user-msg">
          <div>{turn.user_message}</div>
          {turn.files.length > 0 && (
            <div className="user-files">
              {turn.files.map((f) => (
                <span key={f.id} className="file-pill">
                  <span className="file-name">{f.name}</span>
                  <span className="file-size">{fmtBytes(f.size)}</span>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {plan ? (
        <PlanCard
          plan={plan}
          brief={brief}
          status={status}
          onProceed={onProceed}
          onCancel={onCancel}
          collapsed={collapsed && !isLast}
          onToggleCollapsed={() => setCollapsed((v) => !v)}
        />
      ) : (
        <div className="plan-card plan-pending">
          <div className="plan-pending-dot" />
          <span>AGUI is reading the task and choosing the right shape…</span>
        </div>
      )}

      {isAnswerOnly && (turn.answer_text || (turn.final_result as any)?.answer) && (
        <AnswerOnlyBlock text={String(turn.answer_text || (turn.final_result as any)?.answer || "")} />
      )}

      {showStage && !collapsed && (
        <div className="stage-wrap">
          <iframe
            ref={iframeRef}
            className="stage-frame"
            title={`AGUI turn ${turn.id}`}
            sandbox="allow-scripts allow-forms allow-pointer-lock allow-popups"
            src="about:blank"
          />
          {!turn.has_ui && <StageSkeleton brief={brief} />}
        </div>
      )}

      <NarrationStream items={narrations} />

      <div className="turn-footer">
        <span className={`status-pill status-${status}`}>{status}</span>
        {turn.usage?.input_tokens != null && (
          <span className="usage" title="LLM token usage">
            in {turn.usage.input_tokens || 0} · out {turn.usage.output_tokens || 0}
          </span>
        )}
        {status === "running" && (
          <button className="ghost small" onClick={onCancel}>Cancel</button>
        )}
        <button
          className="ghost small"
          onClick={() => setShowInspector((v) => !v)}
        >
          {showInspector ? "Hide inspector" : `Inspector · ${eventsFiltered.length}`}
        </button>
      </div>

      {showInspector && <Inspector events={eventsFiltered} />}
    </article>
  );
}


function PlanCard({
  plan,
  brief,
  status,
  onProceed,
  onCancel,
  collapsed,
  onToggleCollapsed,
}: {
  plan: NonNullable<TurnSnap["plan"]>;
  brief: ReturnType<() => any> | null;
  status: string;
  onProceed: () => void;
  onCancel: () => void;
  collapsed: boolean;
  onToggleCollapsed: () => void;
}) {
  const palette = brief?.palette || {};
  const swatches = Object.entries(palette).slice(0, 6);
  return (
    <div className={`plan-card ${collapsed ? "plan-collapsed" : ""}`}>
      <header className="plan-h">
        <span className="plan-mode">{plan.presentation_mode}</span>
        <span className="plan-concept">{plan.visual_concept}</span>
        <button className="ghost xs" onClick={onToggleCollapsed}>
          {collapsed ? "expand" : "collapse"}
        </button>
      </header>

      {!collapsed && (
        <>
          {plan.rationale && <p className="plan-rationale">{plan.rationale}</p>}

          {brief?.metaphor && (
            <p className="plan-metaphor">
              <span className="kicker">metaphor</span> {brief.metaphor}
            </p>
          )}

          {swatches.length > 0 && (
            <div className="palette">
              {swatches.map(([k, v]) => (
                <span
                  key={k}
                  className="swatch"
                  style={{ background: String(v) }}
                  title={`${k}: ${v}`}
                />
              ))}
            </div>
          )}

          {plan.steps && plan.steps.length > 0 && (
            <ol className="steps">
              {plan.steps.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ol>
          )}

          {plan.tool_hints && plan.tool_hints.length > 0 && (
            <div className="hints">
              {plan.tool_hints.map((t) => (
                <span key={t} className="tag">
                  {t}
                </span>
              ))}
            </div>
          )}

          {brief?.inspirations && brief.inspirations.length > 0 && (
            <p className="inspirations">
              <span className="kicker">inspirations</span>{" "}
              {brief.inspirations.join(" · ")}
            </p>
          )}
        </>
      )}

      {status === "awaiting_steer" && (
        <div className="plan-steer">
          <span className="steer-prompt">Proceed with this approach?</span>
          <button className="ghost" onClick={onCancel}>Cancel</button>
          <button className="primary small" onClick={onProceed}>Proceed</button>
        </div>
      )}
    </div>
  );
}


function StageSkeleton({ brief }: { brief: any }) {
  const palette = brief?.palette || {};
  const bg = palette.bg || palette.background || "#0d1015";
  const ink = palette.ink || palette.fg || "#c9d3e3";
  const accent = palette.accent || "#7aa2ff";
  return (
    <div className="stage-skeleton" style={{ background: bg, color: ink }}>
      <div className="skeleton-bar" style={{ background: accent }} />
      <div className="skeleton-msg">Designing — {brief?.metaphor || "task-specific interface"}…</div>
    </div>
  );
}


function AnswerOnlyBlock({ text }: { text: string }) {
  const blocks = text.split(/\n\n+/);
  return (
    <div className="answer-only">
      {blocks.map((b, i) => (
        <p key={i}>{b}</p>
      ))}
    </div>
  );
}


function NarrationStream({ items }: { items: Array<{ text: string; tone: string; ts: number }> }) {
  const last = items[items.length - 1];
  if (!last) return null;
  return (
    <div className={`narration tone-${last.tone}`}>
      <span className="narration-pulse" />
      <span className="narration-text">{last.text}</span>
    </div>
  );
}


function Inspector({ events }: { events: TaskEvent[] }) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [events.length]);
  return (
    <div className="inspector" ref={ref}>
      {events.map((ev, i) => (
        <div key={i} className={`ev ev-${ev.type}`}>
          <span className="ev-ts">{fmtTime(ev.ts)}</span>
          <span className="ev-label">{ev.type}</span>
          <span className="ev-summary">{summarize(ev)}</span>
        </div>
      ))}
    </div>
  );
}

function summarize(ev: TaskEvent): string {
  const t = ev.type;
  if (t === "tool_called") return `${(ev as any).tool}  ${(ev as any).risk}`;
  if (t === "tool_result") return `${(ev as any).tool}`;
  if (t === "tool_error") return `${(ev as any).tool}: ${(ev as any).message}`;
  if (t === "log") return `[${(ev as any).level}] ${(ev as any).message}`;
  if (t === "state_patch") return Object.keys((ev as any).patch || {}).join(", ");
  if (t === "narration") return String((ev as any).text || "");
  if (t === "ui_ready") return `${(ev as any).bytes} bytes`;
  if (t === "approval_required") return `${(ev as any).tool}`;
  if (t === "failed") return String((ev as any).message || "");
  return "";
}

function fmtTime(ts: unknown): string {
  if (typeof ts !== "number") return "";
  const d = new Date(ts * 1000);
  return d.toTimeString().slice(0, 8);
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KB`;
  return `${(n / 1024 / 1024).toFixed(1)}MB`;
}
