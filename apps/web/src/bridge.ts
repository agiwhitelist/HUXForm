/* AGUI bridge: glues a sandboxed iframe to a turn on the backend.
 *
 * Each turn gets its own Bridge instance. The bridge:
 *   - opens an SSE stream to /api/turns/{id}/events,
 *   - re-broadcasts every event to the iframe via postMessage,
 *   - proxies window.agui.* calls from the iframe to backend tool routes,
 *   - surfaces approval requests (both backend tool approvals and iframe-
 *     initiated custom asks) for the host React app to display.
 */

export type TaskEvent = {
  type: string;
  ts?: number;
  [k: string]: unknown;
};

export type ApprovalRequest = {
  id: string;            // internal id stable for this request
  source: "iframe" | "backend";
  label: string;
  details?: unknown;
  approvalId?: string;   // only set for source=backend
  turnId: string;
};

export type BridgeOptions = {
  iframe: HTMLIFrameElement;
  turnId: string;
  onEvent?: (ev: TaskEvent) => void;
  onApprovalRequest?: (req: ApprovalRequest) => void;
};

export class Bridge {
  private iframe: HTMLIFrameElement;
  private turnId: string;
  private onEvent?: (ev: TaskEvent) => void;
  private onApprovalRequest?: (req: ApprovalRequest) => void;
  private es: EventSource | null = null;
  private listener: (e: MessageEvent) => void;
  private booted = false;
  private bootPayload: object | null = null;
  private eventHistory: TaskEvent[] = [];
  private pendingFrontApprovals = new Map<string, (ok: boolean) => void>();
  private nextApprovalId = 1;
  private destroyed = false;

  constructor(opts: BridgeOptions) {
    this.iframe = opts.iframe;
    this.turnId = opts.turnId;
    this.onEvent = opts.onEvent;
    this.onApprovalRequest = opts.onApprovalRequest;
    this.listener = (e) => this.handleMessage(e);
    window.addEventListener("message", this.listener);
  }

  attachEventStream() {
    if (this.es) return;
    const url = `/api/turns/${this.turnId}/events`;
    this.es = new EventSource(url);
    const handler = (msg: MessageEvent) => {
      try {
        this.dispatchEvent(JSON.parse(msg.data));
      } catch {
        // ignore
      }
    };
    this.es.onmessage = handler;
    [
      "turn_created", "planning_started", "plan_ready", "awaiting_steer",
      "research_started", "research_step", "research_done", "research_failed",
      "codegen_started", "codegen_chunk", "ui_ready", "regenerating", "running",
      "tool_called", "tool_result", "tool_error", "tool_denied", "tool_dry_run",
      "approval_required", "state_patch", "log", "narration",
      "file_attached",
      "final_result", "failed", "cancelled", "heartbeat",
    ].forEach((t) =>
      this.es!.addEventListener(t, handler as EventListener),
    );
  }

  setBootPayload(payload: object) {
    this.bootPayload = payload;
    if (this.booted) this.sendBoot();
  }

  resolveBackendApproval(approvalId: string, approved: boolean) {
    fetch(`/api/turns/${this.turnId}/approve`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ approval_id: approvalId, approved }),
    }).catch(() => {});
  }

  resolveIframeApproval(id: string, approved: boolean) {
    const cb = this.pendingFrontApprovals.get(id);
    if (!cb) return;
    cb(approved);
    this.pendingFrontApprovals.delete(id);
  }

  destroy() {
    this.destroyed = true;
    window.removeEventListener("message", this.listener);
    this.es?.close();
    this.es = null;
  }

  private dispatchEvent(ev: TaskEvent) {
    this.eventHistory.push(ev);
    if (this.eventHistory.length > 800) this.eventHistory.shift();
    this.onEvent?.(ev);

    if (ev.type === "approval_required") {
      this.onApprovalRequest?.({
        id: String(ev.approval_id ?? ""),
        source: "backend",
        approvalId: String(ev.approval_id ?? ""),
        label: String(ev.tool_title ?? ev.tool ?? "Action requires approval"),
        details: ev,
        turnId: this.turnId,
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
      taskId: this.turnId,
    });
  }

  private postToIframe(msg: unknown) {
    const w = this.iframe.contentWindow;
    if (!w) return;
    w.postMessage(msg, "*");
  }

  private async handleMessage(e: MessageEvent) {
    if (this.destroyed) return;
    const data = e.data;
    if (!data || typeof data !== "object" || !(data as any).__agui) return;
    if (e.source !== this.iframe.contentWindow) return;
    const kind = (data as any).kind;

    if (kind === "ready") {
      this.booted = true;
      this.sendBoot();
      return;
    }

    if (kind === "call") {
      const { id, name, params } = data as { id: string; name: string; params: unknown };
      try {
        const res = await fetch(
          `/api/turns/${this.turnId}/tools/${encodeURIComponent(name)}`,
          {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify(params ?? {}),
          },
        );
        const body = await res.json().catch(() => ({}));
        if (!res.ok) {
          this.postToIframe({
            __agui: true, kind: "response", id, ok: false,
            error: body?.detail || `HTTP ${res.status}`,
          });
        } else {
          this.postToIframe({
            __agui: true, kind: "response", id, ok: true, result: body.result,
          });
        }
      } catch (err: any) {
        this.postToIframe({
          __agui: true, kind: "response", id, ok: false,
          error: String(err?.message ?? err),
        });
      }
      return;
    }

    if (kind === "upload") {
      const { id, file, name } = data as {
        id: string;
        file: Blob;
        name: string;
      };
      try {
        if (!(file instanceof Blob)) {
          throw new Error("uploadFile: payload is not a Blob/File");
        }
        // Re-read the cross-origin Blob into a same-origin one so the
        // browser doesn't taint the FormData request.
        const buf = await file.arrayBuffer();
        const localBlob = new Blob([buf], { type: file.type || "application/octet-stream" });
        const form = new FormData();
        const filename = name || "upload";
        form.append("file", localBlob, filename);
        const up = await fetch("/api/files", { method: "POST", body: form });
        const upBody = await up.json().catch(() => ({}));
        if (!up.ok) {
          throw new Error(upBody?.detail || `HTTP ${up.status}`);
        }
        const rec = upBody.file;
        // Attach to this turn so files.read can resolve it.
        await fetch(`/api/turns/${this.turnId}/files`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ file_id: rec.id }),
        }).catch(() => {});
        this.postToIframe({
          __agui: true, kind: "response", id, ok: true, result: rec,
        });
      } catch (err: any) {
        this.postToIframe({
          __agui: true, kind: "response", id, ok: false,
          error: String(err?.message ?? err),
        });
      }
      return;
    }

    if (kind === "evolve") {
      const { id, refine_note } = data as { id: string; refine_note: string };
      try {
        const res = await fetch(`/api/turns/${this.turnId}/regenerate`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ refine_note: String(refine_note || "") }),
        });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) {
          this.postToIframe({
            __agui: true, kind: "response", id, ok: false,
            error: body?.detail || `HTTP ${res.status}`,
          });
        } else {
          this.postToIframe({
            __agui: true, kind: "response", id, ok: true, result: body,
          });
        }
      } catch (err: any) {
        this.postToIframe({
          __agui: true, kind: "response", id, ok: false,
          error: String(err?.message ?? err),
        });
      }
      return;
    }

    if (kind === "approval") {
      const { id, label, details } = data as { id: string; label: string; details: unknown };
      const reqId = `front_${this.nextApprovalId++}`;
      const promise = new Promise<boolean>((resolve) => {
        this.pendingFrontApprovals.set(reqId, resolve);
      });
      this.onApprovalRequest?.({
        id: reqId,
        source: "iframe",
        label,
        details,
        turnId: this.turnId,
      });
      const approved = await promise;
      this.postToIframe({
        __agui: true, kind: "response", id, ok: true, result: { approved },
      });
      return;
    }
  }
}
