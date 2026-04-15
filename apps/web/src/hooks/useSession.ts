// useSession - React hook for session management

import { useState, useCallback, useEffect } from 'react';

export interface Session {
  id: string;
  name: string;
  createdAt: Date;
  updatedAt: Date;
}

const generateSessionId = (): string => {
  return `session_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
};

const generateSessionName = (): string => {
  const now = new Date();
  const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return `Session ${timeStr}`;
};

export function useSession() {
  const [currentSession, setCurrentSession] = useState<Session | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);

  // Create a new session
  const createSession = useCallback((): Session => {
    const now = new Date();
    const newSession: Session = {
      id: generateSessionId(),
      name: generateSessionName(),
      createdAt: now,
      updatedAt: now,
    };
    setCurrentSession(newSession);
    return newSession;
  }, []);

  // Switch to a different session
  const switchSession = useCallback((sessionId: string) => {
    const session = sessions.find(s => s.id === sessionId);
    if (session) {
      setCurrentSession({ ...session, updatedAt: new Date() });
    }
  }, [sessions]);

  // Update current session's updatedAt timestamp
  const touchSession = useCallback(() => {
    if (currentSession) {
      setCurrentSession(prev => prev ? { ...prev, updatedAt: new Date() } : null);
    }
  }, [currentSession]);

  // Rename a session
  const renameSession = useCallback((sessionId: string, newName: string) => {
    setSessions(prev => prev.map(s =>
      s.id === sessionId ? { ...s, name: newName, updatedAt: new Date() } : s
    ));
    if (currentSession?.id === sessionId) {
      setCurrentSession(prev => prev ? { ...prev, name: newName, updatedAt: new Date() } : null);
    }
  }, [currentSession]);

  // Delete a session
  const deleteSession = useCallback((sessionId: string) => {
    setSessions(prev => prev.filter(s => s.id !== sessionId));
    if (currentSession?.id === sessionId) {
      setCurrentSession(null);
    }
  }, [currentSession]);

  // Initialize sessions from localStorage
  useEffect(() => {
    try {
      const stored = localStorage.getItem('agui_sessions');
      if (stored) {
        const parsed = JSON.parse(stored);
        const hydrated = parsed.map((s: Session) => ({
          ...s,
          createdAt: new Date(s.createdAt),
          updatedAt: new Date(s.updatedAt),
        }));
        setSessions(hydrated);
      }
    } catch {
      console.warn('Failed to load sessions from localStorage');
    }
  }, []);

  // Persist sessions to localStorage
  useEffect(() => {
    try {
      localStorage.setItem('agui_sessions', JSON.stringify(sessions));
    } catch {
      console.warn('Failed to save sessions to localStorage');
    }
  }, [sessions]);

  // Add session to list when created
  const addSession = useCallback((session: Session) => {
    setSessions(prev => [session, ...prev]);
  }, []);

  return {
    currentSession,
    sessions,
    createSession,
    switchSession,
    touchSession,
    renameSession,
    deleteSession,
    addSession,
    setCurrentSession,
    setSessions,
  };
}

export default useSession;
