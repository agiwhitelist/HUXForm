// SessionSelector - Session switcher dropdown

import React, { useState, useRef, useEffect } from 'react';
import { Session } from '../hooks/useSession';

interface SessionSelectorProps {
  currentSession: Session | null;
  onSessionSelect: (session: Session) => void;
  onNewSession: () => void;
  sessions: Session[];
}

export function SessionSelector({
  currentSession,
  onSessionSelect,
  onNewSession,
  sessions,
}: SessionSelectorProps): React.ReactElement {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Close dropdown on escape
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
      return () => document.removeEventListener('keydown', handleKeyDown);
    }
  }, [isOpen]);

  const handleSelectSession = (session: Session) => {
    onSessionSelect(session);
    setIsOpen(false);
  };

  const handleNewSession = () => {
    onNewSession();
    setIsOpen(false);
  };

  const displayName = currentSession?.name || 'New Chat';

  return (
    <div className="session-selector" ref={dropdownRef}>
      <button
        className="session-selector-trigger"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        aria-label="Select session"
      >
        <span className="session-selector-label">{displayName}</span>
        <svg
          className={`session-selector-arrow ${isOpen ? 'open' : ''}`}
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {isOpen && (
        <div className="session-selector-dropdown" role="listbox">
          <div className="dropdown-header">
            <span className="dropdown-title">Conversations</span>
          </div>

          <div className="dropdown-items">
            {/* New Chat Option */}
            <button
              className="dropdown-item new-chat"
              onClick={handleNewSession}
              role="option"
              aria-selected={!currentSession}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 5v14M5 12h14" />
              </svg>
              <span>New Chat</span>
            </button>

            {/* Divider */}
            {sessions.length > 0 && <div className="dropdown-divider" />}

            {/* Recent Sessions */}
            {sessions.length > 0 ? (
              <div className="sessions-group">
                <span className="sessions-group-label">Recent</span>
                {sessions.slice(0, 5).map(session => (
                  <button
                    key={session.id}
                    className={`dropdown-item ${currentSession?.id === session.id ? 'active' : ''}`}
                    onClick={() => handleSelectSession(session)}
                    role="option"
                    aria-selected={currentSession?.id === session.id}
                  >
                    <span className="session-name">{session.name}</span>
                  </button>
                ))}
              </div>
            ) : (
              <div className="dropdown-empty">
                <span>No recent conversations</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default SessionSelector;
