/* Browser-side voice input.
 *
 * Holds a MediaRecorder for the duration of a press-and-hold (or click-to-
 * toggle) capture, then ships the recorded blob to /api/voice/transcribe
 * and yields a transcript. Auto-degrades when the host hasn't set up
 * vibevoice.cpp — the caller can check api.voiceHealth() first.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

type State = "idle" | "asking" | "recording" | "transcribing" | "error";

export function useMic(opts: {
  onTranscript: (text: string) => void;
  onError?: (message: string) => void;
}) {
  const [state, setState] = useState<State>("idle");
  const [available, setAvailable] = useState<boolean | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  const recRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  // Check backend availability once.
  useEffect(() => {
    let live = true;
    api.voiceHealth()
      .then((h) => {
        if (!live) return;
        setAvailable(h.available);
        setReason(h.reason ?? null);
      })
      .catch(() => {
        if (!live) return;
        setAvailable(false);
        setReason("voice health check failed");
      });
    return () => { live = false; };
  }, []);

  const cleanup = useCallback(() => {
    try { recRef.current?.stream.getTracks().forEach((t) => t.stop()); } catch {}
    try { streamRef.current?.getTracks().forEach((t) => t.stop()); } catch {}
    recRef.current = null;
    streamRef.current = null;
    chunksRef.current = [];
  }, []);

  const start = useCallback(async () => {
    if (state !== "idle") return;
    if (!navigator.mediaDevices?.getUserMedia) {
      opts.onError?.("microphone API not supported in this browser");
      setState("error");
      return;
    }
    setState("asking");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mime = pickMime();
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      recRef.current = rec;
      chunksRef.current = [];
      rec.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };
      rec.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" });
        cleanup();
        if (blob.size === 0) {
          setState("idle");
          return;
        }
        setState("transcribing");
        try {
          const ext = (rec.mimeType || "audio/webm").includes("wav") ? "wav"
                    : (rec.mimeType || "audio/webm").includes("ogg") ? "ogg"
                    : "webm";
          const res = await api.voiceTranscribe(blob, `speech.${ext}`);
          opts.onTranscript(res.text);
          setState("idle");
        } catch (e: any) {
          opts.onError?.(e?.message ?? String(e));
          setState("error");
        }
      };
      rec.start();
      setState("recording");
    } catch (e: any) {
      cleanup();
      opts.onError?.(e?.message ?? String(e));
      setState("error");
    }
  }, [state, cleanup, opts]);

  const stop = useCallback(() => {
    if (state !== "recording") return;
    try { recRef.current?.stop(); } catch { cleanup(); setState("idle"); }
  }, [state, cleanup]);

  const toggle = useCallback(() => {
    if (state === "idle" || state === "error") return start();
    if (state === "recording") return stop();
    return Promise.resolve();
  }, [state, start, stop]);

  return { state, available, reason, toggle, start, stop };
}


function pickMime(): string | null {
  if (typeof MediaRecorder === "undefined") return null;
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/mp4",
  ];
  for (const c of candidates) {
    if (MediaRecorder.isTypeSupported(c)) return c;
  }
  return null;
}
