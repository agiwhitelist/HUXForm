// HistorySidebar - Neumorphic sidebar with past conversations

import React, { useState, useMemo, useEffect, useRef } from 'react';
import { Session } from '../hooks/useSession';
import { ActionButton } from './ActionButton';

interface HistorySidebarProps {
  sessions: Session[];
  currentSession: Session | null;
  onSessionSelect: (session: Session) => void;
  onNewSession: () => void;
  onDeleteSession: (sessionId: string) => void;
  onRenameSession: (sessionId: string, newName: string) => void;
  onClose: () => void;
  isOpen: boolean;
}

export function HistorySidebar({
  sessions,
  currentSession,
  onSessionSelect,
  onNewSession,
  onDeleteSession,
  onRenameSession,
  onClose,
  isOpen,
}: HistorySidebarProps): React.ReactElement {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Debounce search input
  useEffect(() => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }
    debounceRef.current = setTimeout(() => {
      setDebouncedQuery(searchQuery);
    }, 200);
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, [searchQuery]);

  // Filter sessions by search query
  const filteredSessions = useMemo(() => {
    if (!debouncedQuery.trim()) {
      return sessions;
    }
    const query = debouncedQuery.toLowerCase();
    return sessions.filter(session => {
      if (session.name.toLowerCase().includes(query)) {
        return true;
      }
      return false;
    });
  }, [sessions, debouncedQuery]);

  const handleStartEdit = (session: Session) => {
    setEditingId(session.id);
    setEditValue(session.name);
  };

  const handleSaveEdit = () => {
    if (editingId && editValue.trim()) {
      onRenameSession(editingId, editValue.trim());
    }
    setEditingId(null);
    setEditValue('');
  };

  const handleCancelEdit = () => {
    setEditingId(null);
    setEditValue('');
  };

  const formatDate = (date: Date): string => {
    const d = new Date(date);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays === 0) {
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } else if (diffDays === 1) {
      return 'Yesterday';
    } else if (diffDays < 7) {
      return d.toLocaleDateString([], { weekday: 'short' });
    } else {
      return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSaveEdit();
    } else if (e.key === 'Escape') {
      handleCancelEdit();
    }
  };

  return (
    <>
      {/* Backdrop */}
      <div
        className={`history-backdrop ${isOpen ? 'open' : ''}`}
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Sidebar */}
      <aside
        className={`history-sidebar ${isOpen ? 'open' : ''}`}
        role="complementary"
        aria-label="Chat history"
      >
        <div className="sidebar-header">
          <h2 className="sidebar-title">History</h2>
          <button
            className="close-button"
            onClick={onClose}
            aria-label="Close sidebar"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="sidebar-actions">
          <ActionButton
            label="New Chat"
            onClick={onNewSession}
            variant="primary"
            size="sm"
            icon={
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 5v14M5 12h14" />
              </svg>
            }
          />
        </div>

        <div className="search-container">
          <input
            type="text"
            className="search-input"
            placeholder="Search sessions..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            aria-label="Search sessions"
          />
          {searchQuery && (
            <button
              className="search-clear"
              onClick={() => setSearchQuery('')}
              aria-label="Clear search"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M18 6L6 18M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>

        <div className="sessions-list">
          {filteredSessions.length === 0 ? (
            searchQuery ? (
              <div className="empty-state">
                <p>No sessions found</p>
                <p className="empty-hint">Try a different search term</p>
              </div>
            ) : (
              <div className="empty-state">
                <p>No conversations yet</p>
                <p className="empty-hint">Start a new chat to see it here</p>
              </div>
            )
          ) : (
            filteredSessions.map(session => (
              <div
                key={session.id}
                className={`session-item ${currentSession?.id === session.id ? 'active' : ''}`}
                onMouseEnter={() => setHoveredId(session.id)}
                onMouseLeave={() => setHoveredId(null)}
              >
                {editingId === session.id ? (
                  <div className="session-edit">
                    <input
                      type="text"
                      className="session-edit-input"
                      value={editValue}
                      onChange={e => setEditValue(e.target.value)}
                      onKeyDown={handleKeyDown}
                      autoFocus
                    />
                    <div className="session-edit-actions">
                      <button
                        className="edit-action save"
                        onClick={handleSaveEdit}
                        aria-label="Save"
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M20 6L9 17l-5-5" />
                        </svg>
                      </button>
                      <button
                        className="edit-action cancel"
                        onClick={handleCancelEdit}
                        aria-label="Cancel"
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M18 6L6 18M6 6l12 12" />
                        </svg>
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <button
                      className="session-content"
                      onClick={() => onSessionSelect(session)}
                    >
                      <span className="session-name">{session.name}</span>
                      <span className="session-date">{formatDate(session.updatedAt)}</span>
                    </button>
                    {hoveredId === session.id && (
                      <div className="session-actions">
                        <button
                          className="session-action"
                          onClick={() => handleStartEdit(session)}
                          aria-label="Rename"
                          title="Rename"
                        >
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
                            <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
                          </svg>
                        </button>
                        <button
                          className="session-action delete"
                          onClick={() => onDeleteSession(session.id)}
                          aria-label="Delete"
                          title="Delete"
                        >
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
                          </svg>
                        </button>
                      </div>
                    )}
                  </>
                )}
              </div>
            ))
          )}
        </div>
      </aside>
    </>
  );
}

export default HistorySidebar;
