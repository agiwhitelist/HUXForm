/* AGUI runtime bridge.
 *
 * The generated UI lives in a sandboxed iframe (`sandbox="allow-scripts"`)
 * with no `allow-same-origin`. That means its `window.agui` global is
 * implemented purely via postMessage round-trips with the parent — there
 * is no shared DOM or cookie access. The parent (this code) routes those
 * messages to the AGUI backend.
 *
 * Wire protocol (parent ↔ iframe):
 *
 *   iframe → parent:
 *     { __agui: true, kind: "call",  id, name, params }
 *     { __agui: true, kind: "approval", id, label, details }
 *     { __agui: true, kind: "ready" }
 *
 *   parent → iframe:
 *     { __agui: true, kind: "boot",     plan, tools, goal, history }
 *     { __agui: true, kind: "event",    event }
 *     { __agui: true, kind: "response", id, ok, result?, error? }
 */

export type TaskEvent = {
  type: string;
  ts?: number;
  [k: string]: unknown;
};

export type BridgeOptions = {
  iframe: HTMLIFrameElement;
  taskId: string;
  onEvent?: (ev: TaskEvent) => void;
  onApprovalRequest?: (req: ApprovalRequest) => void;
};

export type ApprovalRequest = {
  id: string;
  source: "iframe" | "backend";
  label: string;
  details?: unknown;
  approvalId?: string;
};

export class Bridge {
  private iframe: HTMLIFrameElement;
  private taskId: string;
  private onEvent?: (ev: TaskEvent) => void;
  private onApprovalRequest?: (req: ApprovalRequest) => void;
  private es: EventSource | null = null;
  private listener: (e: MessageEvent) => void;
  private booted = false;
  private bootPayload: object | null = null;
  private eventHistory: TaskEvent[] = [];
  private pendingFrontApprovals = new Map<
    string,
    { resolve: (ok: boolean) => void }
  >();
  private nextApprovalId = 1;

  constructor(opts: BridgeOptions) {
    this.iframe = opts.iframe;
    this.taskId = opts.taskId;
    this.onEvent = opts.onEvent;
    this.onApprovalRequest = opts.onApprovalRequest;
    this.listener = (e) => this.handleMessage(e);
    window.addEventListener("message", this.listener);
  }

  attachEventStream() {
    if (this.es) return;
    this.es = new EventSource(`/api/tasks/${this.taskId}/events`);
    // Use the generic "message" listener; we get type from the event payload.
    this.es.onmessage = (msg) => this.dispatchEvent(JSON.parse(msg.data));
    // Some browsers/servers emit named events too. Listen to the relevant ones.
    [
      "task_created",
      "planning_started",
      "plan_ready",
      "codegen_started",
      "ui_ready",
      "running",
      "tool_called",
      "tool_result",
      "tool_error",
      "tool_denied",
      "approval_required",
      "state_patch",
      "log",
      "final_result",
      "failed",
      "heartbeat",
    ].forEach((t) =>
      this.es!.addEventListener(t, (msg: MessageEvent) =>
        this.dispatchEvent(JSON.parse(msg.data)),
      ),
    );
    this.es.onerror = () => {
      // EventSource auto-reconnects; nothing to do.
    };
  }

  setBootPayload(payload: object) {
    this.bootPayload = payload;
    if (this.booted) this.sendBoot();
  }

  resolveBackendApproval(approvalId: string, approved: boolean) {
    fetch(`/api/tasks/${this.taskId}/approve`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ approval_id: approvalId, approved }),
    }).catch(() => {});
  }

  resolveIframeApproval(id: string, approved: boolean) {
    const pending = this.pendingFrontApprovals.get(id);
    if (!pending) return;
    pending.resolve(approved);
    this.pendingFrontApprovals.delete(id);
  }

  destroy() {
    window.removeEventListener("message", this.listener);
    this.es?.close();
    this.es = null;
  }

  private dispatchEvent(ev: TaskEvent) {
    this.eventHistory.push(ev);
    if (this.eventHistory.length > 500) this.eventHistory.shift();
    this.onEvent?.(ev);

    if (ev.type === "approval_required") {
      this.onApprovalRequest?.({
        id: String(ev.approval_id ?? ""),
        source: "backend",
        approvalId: String(ev.approval_id ?? ""),
        label: String(ev.tool_title ?? ev.tool ?? "Action requires approval"),
        details: ev,
      });
    }

    this.postToIframe({ __agui: true, kind: "event", event: ev });
  }

  private sendBoot() {
    if (!this.bootPayload) return;
    this.postToIframe({
      __agui: true,
      kind: "boot",
      ...this.bootPayload,
      history: this.eventHistory,
      taskId: this.taskId,
    });
  }

  private postToIframe(msg: unknown) {
    const w = this.iframe.contentWindow;
    if (!w) return;
    w.postMessage(msg, "*");
  }

  private async handleMessage(e: MessageEvent) {
    const data = e.data;
    if (!data || typeof data !== "object" || !(data as any).__agui) return;
    if ((data as any).source === "parent") return; // ignore echoes
    const kind = (data as any).kind;

    if (kind === "ready") {
      this.booted = true;
      this.sendBoot();
      return;
    }

    if (kind === "call") {
      const { id, name, params } = data as {
        id: string;
        name: string;
        params: unknown;
      };
      try {
        const res = await fetch(
          `/api/tasks/${this.taskId}/tools/${encodeURIComponent(name)}`,
          {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify(params ?? {}),
          },
        );
        const body = await res.json().catch(() => ({}));
        if (!res.ok) {
          this.postToIframe({
            __agui: true,
            kind: "response",
            id,
            ok: false,
            error: body?.detail || `HTTP ${res.status}`,
          });
        } else {
          this.postToIframe({
            __agui: true,
            kind: "response",
            id,
            ok: true,
            result: body.result,
          });
        }
      } catch (err: any) {
        this.postToIframe({
          __agui: true,
          kind: "response",
          id,
          ok: false,
          error: String(err?.message ?? err),
        });
      }
      return;
    }

    if (kind === "approval") {
      const { id, label, details } = data as {
        id: string;
        label: string;
        details: unknown;
      };
      const reqId = `front_${this.nextApprovalId++}`;
      const promise = new Promise<boolean>((resolve) => {
        this.pendingFrontApprovals.set(reqId, { resolve });
      });
      this.onApprovalRequest?.({
        id: reqId,
        source: "iframe",
        label,
        details,
      });
      const approved = await promise;
      this.postToIframe({
        __agui: true,
        kind: "response",
        id,
        ok: true,
        result: { approved },
      });
      return;
    }
  }
}

