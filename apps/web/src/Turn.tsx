/* AGUI Stage.
 *
 * The current turn IS the screen. Top thin "scribe" ribbon narrates what
 * the agent is doing. The generated iframe fills everything below it. A
 * follow-up bar lives at the bottom for refinements; the inspector hides
 * to the side until you ask.
 *
 * No plan card by default. No event log on the page. The shell is silent
 * unless the agent explicitly asks the human for a steering decision.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { api, FileRec, Turn as TurnSnap } from "./api";
import { ApprovalRequest, Bridge, TaskEvent } from "./bridge";

type Tool = {
  name: string;
  title: string;
  description: string;
  risk: string;
  source: string;
  requires_approval: boolean;
};

export function Stage(props: {
  turn: TurnSnap;
  tools: Tool[];
  inspectorOpen: boolean;
  onToggleInspector: () => void;
  onApprovalRequest: (req: ApprovalRequest) => void;
  onTurnUpdated: (turn: TurnSnap) => void;
  onFollowUp: (goal: string, fileIds: string[]) => Promise<void>;
  registerBridge: (id: string, bridge: Bridge | null) => void;
}) {
  const [turn, setTurn] = useState<TurnSnap>(props.turn);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [latestNarration, setLatestNarration] = useState<string>("");
  const [iframeLoaded, setIframeLoaded] = useState(false);

  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const bridgeRef = useRef<Bridge | null>(null);
  const onApprovalRef = useRef(props.onApprovalRequest);
  onApprovalRef.current = props.onApprovalRequest;
  const onTurnUpdatedRef = useRef(props.onTurnUpdated);
  onTurnUpdatedRef.current = props.onTurnUpdated;
  const uiVersionRef = useRef(0);

  // refresh local snapshot if parent gives a new turn (e.g. follow-up landed)
  useEffect(() => {
    setTurn(props.turn);
    setEvents([]);
    setLatestNarration("");
    setIframeLoaded(false);
  }, [props.turn.id]);

  // bridge + SSE; restarts when turn id changes
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
        if (ev.type === "narration" && typeof (ev as any).text === "string") {
          setLatestNarration(String((ev as any).text));
        }
        if (ev.type === "plan_ready" && ev.plan) {
          setTurn((p) => ({ ...p, plan: ev.plan as any, status: "awaiting_steer" }));
        } else if (ev.type === "awaiting_steer") {
          setTurn((p) => ({ ...p, status: "awaiting_steer" }));
        } else if (ev.type === "codegen_started") {
          setTurn((p) => ({ ...p, status: "generating" }));
          // Point the iframe at the streaming endpoint NOW so it starts
          // receiving chunks while the LLM is still generating. The
          // browser parses the response progressively — no per-chunk
          // srcDoc swap, no flicker. The endpoint sends the runtime stub
          // and any deferred <script> blocks at the end so the bridge
          // wakes up cleanly when the stream closes.
          const f = iframeRef.current;
          if (f) {
            uiVersionRef.current += 1;
            f.removeAttribute("srcdoc");
            f.src = `/api/turns/${turn.id}/ui-stream?v=${uiVersionRef.current}&t=${Date.now()}`;
            setIframeLoaded(true);
          }
        } else if (ev.type === "ui_ready") {
          setTurn((p) => ({ ...p, has_ui: true, status: "running" }));
        } else if (ev.type === "regenerating") {
          setTurn((p) => ({ ...p, status: "generating" }));
          setIframeLoaded(false);
          // agui.evolve / manual regenerate — reload the iframe through
          // the streaming endpoint so the new document is drawn live too.
          const f = iframeRef.current;
          if (f) {
            uiVersionRef.current += 1;
            f.removeAttribute("srcdoc");
            f.src = `/api/turns/${turn.id}/ui-stream?v=${uiVersionRef.current}&t=${Date.now()}`;
            setIframeLoaded(true);
          }
        } else if (ev.type === "running") {
          setTurn((p) => ({ ...p, status: "running" }));
        } else if (ev.type === "research_done") {
          setTurn((p) => ({
            ...p,
            state: {
              ...(p.state || {}),
              research: {
                summary: (ev as any).summary ?? "",
                steps: ((p.state as any)?.research?.steps) ?? [],
                stopped: (ev as any).stopped ?? "",
              },
            },
          }));
        } else if (ev.type === "final_result") {
          setTurn((p) => ({
            ...p,
            status: "done",
            final_result: (ev as any).result ?? null,
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
    props.registerBridge(turn.id, bridge);
    return () => {
      props.registerBridge(turn.id, null);
      bridge.destroy();
      bridgeRef.current = null;
    };
  }, [turn.id]);

  // ship boot payload to iframe when plan is known
  useEffect(() => {
    if (!bridgeRef.current || !turn.plan) return;
    bridgeRef.current.setBootPayload({
      plan: turn.plan,
      tools: props.tools,
      goal: turn.user_message,
      files: turn.files,
      research: (turn.state as any)?.research ?? null,
    });
  }, [turn.plan, props.tools, turn.user_message, turn.files, turn.state]);

  // If the iframe didn't start streaming yet (e.g. we restored a prior
  // turn whose status is already past codegen_started), fall back to the
  // cached final HTML at /ui.
  useEffect(() => {
    if (!turn.has_ui) return;
    const f = iframeRef.current;
    if (!f || iframeLoaded) return;
    f.removeAttribute("srcdoc");
    f.src = `/api/turns/${turn.id}/ui?t=${Date.now()}`;
    setIframeLoaded(true);
  }, [turn.has_ui, turn.id, iframeLoaded]);

  // bubble snapshot up
  useEffect(() => {
    onTurnUpdatedRef.current(turn);
  }, [turn]);

  const onProceed = useCallback(async () => {
    try { await api.proceed(turn.id); } catch {}
  }, [turn.id]);

  const onCancel = useCallback(async () => {
    try { await api.cancel(turn.id); } catch {}
  }, [turn.id]);

  const onRegenerate = useCallback(async () => {
    try { await api.regenerate(turn.id, undefined); } catch {}
  }, [turn.id]);

  const brief = turn.plan?.visual_brief || null;
  const status = turn.status;
  const isAwaitingSteer = status === "awaiting_steer";
  const liveStep = useMemo(() => {
    return scribeFromEvents(events, turn);
  }, [events, turn]);

  const tokensSummary = useMemo(() => {
    const i = turn.usage?.input_tokens ?? 0;
    const o = turn.usage?.output_tokens ?? 0;
    if (!i && !o) return "";
    return `${humanize(i)} ↘  ${humanize(o)} ↗`;
  }, [turn.usage?.input_tokens, turn.usage?.output_tokens]);

  return (
    <section className="stage-app">
      <Scribe
        goal={turn.user_message}
        live={latestNarration || liveStep}
        status={status}
        tokens={tokensSummary}
        canCancel={status === "running" || status === "generating" || status === "planning"}
        onCancel={onCancel}
        onRegenerate={onRegenerate}
        onInspector={props.onToggleInspector}
        canRegenerate={status === "done" || status === "running" || status === "failed"}
      />

      <div className="stage-canvas">
        <iframe
          ref={iframeRef}
          className="stage-frame"
          title={`agui-${turn.id}`}
          sandbox="allow-scripts allow-forms allow-pointer-lock allow-popups allow-modals"
          src="about:blank"
        />

        {!iframeLoaded && !turn.has_ui && status !== "failed" && (
          <Curtain plan={turn.plan} brief={brief} status={status} />
        )}

        {status === "failed" && <FailCard message={turn.error || "Something went wrong."} />}

        {isAwaitingSteer && (
          <SteerOverlay
            concept={turn.plan?.visual_concept || ""}
            rationale={turn.plan?.rationale || ""}
            onProceed={onProceed}
            onCancel={onCancel}
          />
        )}
      </div>

      <FollowUp onSend={props.onFollowUp} disabled={status === "planning" || status === "generating"} />

      {props.inspectorOpen && (
        <Inspector
          plan={turn.plan}
          events={events}
          onClose={props.onToggleInspector}
        />
      )}
    </section>
  );
}


/* -------------------------------------------------------------------- */
/* Scribe ribbon — the only chrome above the iframe                      */
/* -------------------------------------------------------------------- */

function Scribe(props: {
  goal: string;
  live: string;
  status: string;
  tokens: string;
  canCancel: boolean;
  onCancel: () => void;
  onRegenerate: () => void;
  canRegenerate: boolean;
  onInspector: () => void;
}) {
  const showDot = props.status === "planning" || props.status === "generating" || props.status === "running";
  return (
    <header className="scribe">
      <span className="scribe-goal">{props.goal}</span>
      <span className="scribe-sep" />
      <span className="scribe-step">
        {showDot && <span className="scribe-dot" />}
        <span>{props.live || statusPhrase(props.status)}</span>
      </span>
      {props.tokens && <span className="scribe-meta">{props.tokens}</span>}
      <div className="scribe-actions">
        {props.canRegenerate && (
          <button onClick={props.onRegenerate}>Regenerate</button>
        )}
        {props.canCancel && (
          <button className="danger" onClick={props.onCancel}>
            Cancel
          </button>
        )}
        <button onClick={props.onInspector}>
          Inspector
        </button>
      </div>
    </header>
  );
}


/* -------------------------------------------------------------------- */
/* Curtain — what the user sees while codegen is still drawing the UI    */
/* -------------------------------------------------------------------- */

function Curtain(props: {
  plan: TurnSnap["plan"];
  brief: any;
  status: string;
}) {
  const palette = props.brief?.palette || {};
  const cols = Object.values(palette).filter(Boolean).slice(0, 6) as string[];
  const concept = props.plan?.visual_concept || "";
  const metaphor = props.brief?.metaphor || "";
  const phase = props.status;

  return (
    <div className={`stage-curtain ${phase === "running" ? "gone" : ""}`}>
      <div className="curtain-inner">
        <div className="curtain-meta">{phaseLabel(phase)}</div>
        {concept ? (
          <h3 className="curtain-concept">{prettyConcept(concept)}</h3>
        ) : (
          <h3 className="curtain-concept">choosing a shape…</h3>
        )}
        {metaphor && <p className="curtain-metaphor">{metaphor}</p>}
        {cols.length > 0 && (
          <div className="curtain-swatch">
            {cols.map((c, i) => (
              <span key={i} style={{ background: c }} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function FailCard(props: { message: string }) {
  return (
    <div className="fail-card">
      <span className="fail-h">The pipeline broke</span>
      <span className="fail-msg">{props.message}</span>
    </div>
  );
}


/* -------------------------------------------------------------------- */
/* Steer overlay — only when director asked for explicit confirmation    */
/* -------------------------------------------------------------------- */

function SteerOverlay(props: {
  concept: string;
  rationale: string;
  onProceed: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="steer-overlay">
      <div className="steer-card">
        <span className="steer-h">Steering check</span>
        <h3 className="steer-q">
          Proceed with <em>{prettyConcept(props.concept) || "this approach"}</em>?
        </h3>
        {props.rationale && <p className="steer-rat">{props.rationale}</p>}
        <div className="steer-row">
          <button onClick={props.onCancel}>Cancel</button>
          <button className="primary" onClick={props.onProceed}>
            Proceed
          </button>
        </div>
      </div>
    </div>
  );
}


/* -------------------------------------------------------------------- */
/* Follow-up — slim, italic, lives below the stage                       */
/* -------------------------------------------------------------------- */

function FollowUp(props: {
  onSend: (goal: string, fileIds: string[]) => Promise<void>;
  disabled: boolean;
}) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<FileRec[]>([]);
  const [busy, setBusy] = useState(false);

  const onSend = async () => {
    if (!text.trim() || busy) return;
    setBusy(true);
    try {
      await props.onSend(text.trim(), files.map((f) => f.id));
      setText("");
      setFiles([]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="followup">
      {files.length > 0 && (
        <div className="followup-files">
          {files.map((f) => (
            <span key={f.id} className="attached-pill">
              <span>{f.name}</span>
              <button onClick={() => setFiles((p) => p.filter((x) => x.id !== f.id))}>×</button>
            </span>
          ))}
        </div>
      )}
      <span className="followup-mark">↳ refine</span>
      <input
        type="text"
        value={text}
        disabled={busy || props.disabled}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onSend();
        }}
        placeholder="another shape, another lens, a smaller scope…"
      />
      <label className="followup-attach">
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
        attach
      </label>
      <button
        className="followup-send"
        onClick={onSend}
        disabled={!text.trim() || busy || props.disabled}
      >
        send
      </button>
    </div>
  );
}


/* -------------------------------------------------------------------- */
/* Inspector drawer                                                      */
/* -------------------------------------------------------------------- */

function Inspector(props: {
  plan: TurnSnap["plan"];
  events: TaskEvent[];
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const filtered = useMemo(
    () => props.events.filter((e) => e.type !== "heartbeat"),
    [props.events],
  );
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [filtered.length]);

  const brief = props.plan?.visual_brief;
  const palette = brief?.palette || ({} as Record<string, string>);
  const swatches = Object.values(palette).filter(Boolean).slice(0, 6) as string[];

  return (
    <aside className="inspector">
      <div className="inspector-h">
        <h3>Inspector</h3>
        <span className="meta">⌘. · {filtered.length} events</span>
      </div>
      {props.plan && (
        <div className="inspector-plan">
          <h4>{props.plan.presentation_mode}</h4>
          <span className="concept">{prettyConcept(props.plan.visual_concept)}</span>
          {brief?.metaphor && <p className="metaphor">{brief.metaphor}</p>}
          {swatches.length > 0 && (
            <div className="swatches">
              {swatches.map((c, i) => (
                <span key={i} style={{ background: c }} />
              ))}
            </div>
          )}
          {props.plan.steps && props.plan.steps.length > 0 && (
            <ol>
              {props.plan.steps.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ol>
          )}
        </div>
      )}
      <div className="inspector-list" ref={ref}>
        {filtered.map((ev, i) => (
          <div key={i} className={`ev ev-${ev.type}`}>
            <span className="ev-ts">{fmtTime(ev.ts)}</span>
            <span className="ev-label">{ev.type}</span>
            <span className="ev-summary">{summarize(ev)}</span>
          </div>
        ))}
      </div>
    </aside>
  );
}


/* -------------------------------------------------------------------- */
/* Helpers                                                               */
/* -------------------------------------------------------------------- */

function statusPhrase(status: string): string {
  switch (status) {
    case "created":      return "reading the task";
    case "planning":     return "deciding what shape to take";
    case "awaiting_steer": return "waiting on your nod";
    case "generating":   return "drawing the interface";
    case "running":      return "alive";
    case "done":         return "finished";
    case "failed":       return "broken";
    case "cancelled":    return "stopped";
    default:             return status;
  }
}

function phaseLabel(status: string): string {
  switch (status) {
    case "planning":   return "phase 01 · planning";
    case "generating": return "phase 02 · drawing";
    case "running":    return "phase 03 · running";
    default:           return `phase · ${status}`;
  }
}

function prettyConcept(s: string): string {
  if (!s) return "";
  return s.replace(/_/g, " ");
}

function scribeFromEvents(events: TaskEvent[], turn: TurnSnap): string {
  if (turn.status === "awaiting_steer") {
    return turn.plan?.visual_concept
      ? `proposing ${prettyConcept(turn.plan.visual_concept)}`
      : "awaiting your nod";
  }
  if (turn.status === "done") return "finished";
  if (turn.status === "cancelled") return "stopped";
  for (let i = events.length - 1; i >= 0; i--) {
    const e: any = events[i];
    if (e.type === "narration") return String(e.text || "");
    if (e.type === "tool_called") return `calling ${e.tool}`;
    if (e.type === "tool_result") return `done ${e.tool}`;
    if (e.type === "codegen_started") return "drawing the interface";
    if (e.type === "planning_started") return "deciding what shape to take";
  }
  return statusPhrase(turn.status);
}

function summarize(ev: TaskEvent): string {
  const t = ev.type;
  const a = ev as any;
  if (t === "tool_called") return `${a.tool}  ${a.risk || ""}`;
  if (t === "tool_result") return `${a.tool}`;
  if (t === "tool_error") return `${a.tool}: ${a.message}`;
  if (t === "log") return `[${a.level}] ${a.message}`;
  if (t === "state_patch") return Object.keys(a.patch || {}).join(", ");
  if (t === "narration") return String(a.text || "");
  if (t === "ui_ready") return `${a.bytes} bytes`;
  if (t === "approval_required") return `${a.tool}`;
  if (t === "failed") return String(a.message || "");
  if (t === "file_attached") return a.file?.name || "";
  return "";
}

function fmtTime(ts: unknown): string {
  if (typeof ts !== "number") return "";
  const d = new Date(ts * 1000);
  return d.toTimeString().slice(0, 8);
}

function humanize(n: number): string {
  if (!n) return "0";
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}
