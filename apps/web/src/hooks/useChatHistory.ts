// useChatHistory - React hook for chat persistence (localStorage)

import { useState, useCallback, useEffect, useRef } from 'react';
import { Session } from './useSession';

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp?: Date;
  metadata?: {
    status?: 'sent' | 'delivered' | 'read';
    error?: boolean;
  };
}

export interface ChatHistory {
  sessionId: string;
  messages: ChatMessage[];
  createdAt: Date;
  updatedAt: Date;
}

const STORAGE_KEY = 'agui_chat_history';

const generateHistoryId = (sessionId: string): string => {
  return `history_${sessionId}`;
};

export function useChatHistory(currentSession: Session | null) {
  const [chatHistory, setChatHistory] = useState<ChatHistory | null>(null);
  const [allHistories, setAllHistories] = useState<Record<string, ChatHistory>>({});
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load all histories from localStorage on mount
  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        const hydrated: Record<string, ChatHistory> = {};
        for (const key of Object.keys(parsed)) {
          const h = parsed[key];
          hydrated[key] = {
            ...h,
            createdAt: new Date(h.createdAt),
            updatedAt: new Date(h.updatedAt),
            messages: h.messages.map((m: ChatMessage) => ({
              ...m,
              timestamp: m.timestamp ? new Date(m.timestamp) : undefined,
            })),
          };
        }
        setAllHistories(hydrated);
      }
    } catch {
      console.warn('Failed to load chat history from localStorage');
    }
  }, []);

  // Load history for current session
  useEffect(() => {
    if (currentSession) {
      const historyId = generateHistoryId(currentSession.id);
      const history = allHistories[historyId];
      if (history) {
        setChatHistory(history);
      } else {
        setChatHistory(null);
      }
    } else {
      setChatHistory(null);
    }
  }, [currentSession, allHistories]);

  // Debounced save to localStorage
  const saveToStorage = useCallback((histories: Record<string, ChatHistory>) => {
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current);
    }
    saveTimeoutRef.current = setTimeout(() => {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(histories));
      } catch {
        console.warn('Failed to save chat history to localStorage');
      }
    }, 300);
  }, []);

  // Add a message to the current session's history
  const addMessage = useCallback((message: ChatMessage) => {
    if (!currentSession) return;

    const historyId = generateHistoryId(currentSession.id);
    const now = new Date();

    setChatHistory(prev => {
      if (!prev) {
        const newHistory: ChatHistory = {
          sessionId: currentSession.id,
          messages: [message],
          createdAt: now,
          updatedAt: now,
        };
        setAllHistories(h => {
          const updated = { ...h, [historyId]: newHistory };
          saveToStorage(updated);
          return updated;
        });
        return newHistory;
      }

      const updated: ChatHistory = {
        ...prev,
        messages: [...prev.messages, message],
        updatedAt: now,
      };
      setAllHistories(h => {
        const newHistories = { ...h, [historyId]: updated };
        saveToStorage(newHistories);
        return newHistories;
      });
      return updated;
    });
  }, [currentSession, saveToStorage]);

  // Clear messages for current session
  const clearHistory = useCallback(() => {
    if (!currentSession) return;

    const historyId = generateHistoryId(currentSession.id);
    setChatHistory(null);
    setAllHistories(h => {
      const updated = { ...h };
      delete updated[historyId];
      saveToStorage(updated);
      return updated;
    });
  }, [currentSession, saveToStorage]);

  // Get history for a specific session
  const getHistoryForSession = useCallback((sessionId: string): ChatHistory | null => {
    const historyId = generateHistoryId(sessionId);
    return allHistories[historyId] || null;
  }, [allHistories]);

  // Delete history for a specific session
  const deleteHistoryForSession = useCallback((sessionId: string) => {
    const historyId = generateHistoryId(sessionId);
    setAllHistories(h => {
      const updated = { ...h };
      delete updated[historyId];
      saveToStorage(updated);
      return updated;
    });
  }, [saveToStorage]);

  // Export chat history as JSON file
  const exportChatHistory = useCallback((sessionId: string) => {
    const historyId = generateHistoryId(sessionId);
    const history = allHistories[historyId];

    if (!history) {
      return false;
    }

    const exportData = {
      sessionId: history.sessionId,
      exportedAt: new Date().toISOString(),
      createdAt: history.createdAt instanceof Date ? history.createdAt.toISOString() : history.createdAt,
      updatedAt: history.updatedAt instanceof Date ? history.updatedAt.toISOString() : history.updatedAt,
      messages: history.messages.map(m => ({
        role: m.role,
        content: m.content,
        timestamp: m.timestamp instanceof Date ? m.timestamp.toISOString() : m.timestamp,
        metadata: m.metadata,
      })),
    };

    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `chat-history-${sessionId}-${Date.now()}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    return true;
  }, [allHistories]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
      }
    };
  }, []);

  return {
    chatHistory,
    allHistories,
    addMessage,
    clearHistory,
    getHistoryForSession,
    deleteHistoryForSession,
    exportChatHistory,
  };
}

export default useChatHistory;
