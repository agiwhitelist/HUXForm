/* Typed wrapper around the AGUI HTTP API. */

export type FileRec = { id: string; name: string; mime: string; size: number };

export type VisualBrief = {
  metaphor: string;
  palette: Record<string, string>;
  typography: Record<string, string>;
  layout: string;
  interaction: string;
  motion: string;
  microcopy_tone: string;
  banned_patterns: string[];
  inspirations: string[];
};

export type TaskPlan = {
  task_type: string;
  presentation_mode: string;
  visual_concept: string;
  rationale: string;
  steps: string[];
  tool_hints: string[];
  needs_user_input: boolean;
  visual_brief: VisualBrief | null;
};

export type Turn = {
  id: string;
  thread_id: string;
  parent_turn_id: string | null;
  user_message: string;
  created_at: number;
  status: string;
  plan: TaskPlan | null;
  answer_text: string | null;
  state: Record<string, unknown>;
  final_result: unknown;
  error: string | null;
  has_ui: boolean;
  files: FileRec[];
  usage: { input_tokens?: number; output_tokens?: number };
};

export type ThreadSummary = {
  id: string;
  title: string;
  created_at: number;
  turn_count: number;
};

export type Thread = {
  id: string;
  title: string;
  created_at: number;
  turns: Turn[];
};

async function jget<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`GET ${path} -> ${r.status}`);
  return (await r.json()) as T;
}

async function jpost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(`POST ${path} -> ${r.status}: ${text}`);
  }
  return (await r.json()) as T;
}

export const api = {
  createThread: (goal: string, file_ids: string[], auto_proceed: boolean) =>
    jpost<{ thread_id: string; turn_id: string }>("/api/threads", {
      goal,
      file_ids,
      auto_proceed,
    }),

  addTurn: (
    thread_id: string,
    goal: string,
    file_ids: string[],
    auto_proceed: boolean,
    parent_turn_id: string | null,
  ) =>
    jpost<{ turn_id: string }>(`/api/threads/${thread_id}/turns`, {
      goal,
      file_ids,
      auto_proceed,
      parent_turn_id,
    }),

  listThreads: () => jget<{ threads: ThreadSummary[] }>("/api/threads"),
  getThread: (id: string) => jget<Thread>(`/api/threads/${id}`),
  getTurn: (id: string) => jget<Turn>(`/api/turns/${id}`),

  proceed: (id: string) => jpost(`/api/turns/${id}/proceed`, {}),
  cancel: (id: string) => jpost(`/api/turns/${id}/cancel`, {}),
  approve: (id: string, approval_id: string, approved: boolean) =>
    jpost(`/api/turns/${id}/approve`, { approval_id, approved }),

  regenerate: (id: string, refine_note?: string) =>
    jpost(`/api/turns/${id}/regenerate`, { refine_note: refine_note || null }),

  uploadFile: async (file: File): Promise<FileRec> => {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch("/api/files", { method: "POST", body: fd });
    if (!r.ok) throw new Error(`upload failed: ${r.status}`);
    const data = (await r.json()) as { file: FileRec };
    return data.file;
  },

  tools: () =>
    jget<{ tools: Array<{ name: string; title: string; description: string; risk: string; requires_approval: boolean; source: string }> }>(
      "/api/tools",
    ),

  audit: (turn_id?: string) =>
    jget<{ entries: Array<{ ts: number; kind: string; data: unknown }> }>(
      `/api/audit${turn_id ? `?turn_id=${encodeURIComponent(turn_id)}` : ""}`,
    ),

  auditStats: () =>
    jget<{
      tools: Array<{ tool: string; count: number; fail: number; total_ms: number; avg_ms: number; p50_ms: number; p95_ms: number; last_ms: number }>;
      totals: { calls: number; total_ms: number };
      usage: { turns: number; input_tokens: number; output_tokens: number };
    }>("/api/audit/stats"),

  capabilities: () =>
    jget<{
      mcp: Array<{
        alias: string; command: string; args: string[];
        install_type: string; source_url: string | null;
        description: string | null; trust_score: number | null;
        running: boolean;
        tools: Array<{ name: string; title: string; risk: string; description: string }>;
      }>;
      openapi: Array<{ alias: string; spec_url: string; base_url: string | null; trust_score: number | null }>;
    }>("/api/capabilities"),

  uninstallCapability: (alias: string) =>
    fetch(`/api/capabilities/mcp/${encodeURIComponent(alias)}`, { method: "DELETE" })
      .then(async (r) => {
        if (!r.ok) throw new Error(`uninstall ${alias} -> ${r.status}: ${await r.text().catch(() => "")}`);
        return r.json();
      }),

  share: (turn_id: string) =>
    jpost<{ token: string; url: string }>(`/api/turns/${turn_id}/share`, { public: true }),

  revokeShare: (token: string) =>
    fetch(`/api/share/${encodeURIComponent(token)}`, { method: "DELETE" })
      .then((r) => { if (!r.ok) throw new Error(`revoke -> ${r.status}`); return r.json(); }),

  route: (thread_id: string, message: string) =>
    jpost<{ action: "refine" | "new_turn"; confidence: number; reason: string; target_turn_id: string | null }>(
      "/api/route", { thread_id, message },
    ),

  presets: () =>
    jget<{
      active: string;
      presets: Record<string, {
        name: string;
        palette: Record<string, string>;
        typography: Record<string, string>;
        banned_extra: string[];
        notes: string;
      }>;
    }>("/api/presets"),

  upsertPreset: (preset: {
    name: string;
    palette?: Record<string, string>;
    typography?: Record<string, string>;
    banned_extra?: string[];
    notes?: string;
  }) => jpost<{ ok: boolean }>("/api/presets", preset),

  activatePreset: (name: string) =>
    jpost<{ ok: boolean; active: string }>("/api/presets/activate", { name }),

  deletePreset: (name: string) =>
    fetch(`/api/presets/${encodeURIComponent(name)}`, { method: "DELETE" })
      .then((r) => { if (!r.ok) throw new Error(`delete preset -> ${r.status}`); return r.json(); }),

  voiceHealth: () =>
    jget<{ available: boolean; reason: string | null; sample_rate: number }>("/api/voice/health"),

  voiceTranscribe: async (blob: Blob, filename = "speech.webm"): Promise<{ text: string }> => {
    const fd = new FormData();
    fd.append("file", blob, filename);
    const r = await fetch("/api/voice/transcribe", { method: "POST", body: fd });
    if (!r.ok) {
      const text = await r.text().catch(() => "");
      throw new Error(`transcribe -> ${r.status}: ${text}`);
    }
    return r.json();
  },

  voiceSynthesize: (text: string, voice?: string) =>
    jpost<{ file: FileRec; sample_rate: number }>("/api/voice/synthesize", { text, voice: voice ?? null }),
};
