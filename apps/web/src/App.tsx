import React, { useState, useCallback, useEffect, useRef } from 'react';
import { Routes, Route, Link, useLocation } from 'react-router-dom';
import { ChatInterface, MessageBubble, UserInput, ActionButton, UISchemaViewer } from './components/neumorphic';
import { LoadingSpinner } from './components/LoadingSpinner';
import { HistorySidebar } from './components/HistorySidebar';
import { SessionSelector } from './components/SessionSelector';
import { UIDocumentRenderer } from './components/UIDocumentRenderer';
import { UIDocument } from './components/registry';
import { useSession } from './hooks/useSession';
import { useChatHistory } from './hooks/useChatHistory';
import { useActions } from './hooks/useActions';

// Collaboration Status Badge Component
interface CollaborationStatusProps {
  isConnected: boolean;
  tabCount: number;
}

function CollaborationStatus({ isConnected, tabCount }: CollaborationStatusProps) {
  return (
    <div className="collaboration-status" title={`${tabCount} tab${tabCount !== 1 ? 's' : ''} connected`}>
      <span className={`status-dot ${isConnected ? 'connected' : 'disconnected'}`} />
      <span className="status-label">{isConnected ? 'Connected' : 'Disconnected'}</span>
      {tabCount > 1 && <span className="tab-count">({tabCount})</span>}
    </div>
  );
}

// Types
interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp?: Date;
  metadata?: {
    status?: 'sent' | 'delivered' | 'read';
    error?: boolean;
    ui_document?: UIDocument;
  };
}

interface UIBlock {
  id: string;
  type: string;
  content: Record<string, unknown>;
  actions?: Array<{
    id: string;
    type: 'button' | 'link' | 'submit' | 'navigate';
    label: string;
    disabled?: boolean;
    icon?: string;
  }>;
  metadata?: Record<string, unknown>;
}

// Chat Page Component
interface ChatPageProps {
  chatHistory: ReturnType<typeof useChatHistory>['chatHistory'];
  addMessage: ReturnType<typeof useChatHistory>['addMessage'];
}

function ChatPage({ chatHistory, addMessage }: ChatPageProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { submitAction } = useActions();

  // Handle actions from UI blocks (forms, buttons, etc.)
  const handleBlockAction = useCallback(async (action: { id: string; type: string; label: string; params?: Record<string, unknown> }) => {
    const result = await submitAction(action.id, action.params || {});
    if (result?.success && result.ui_document) {
      // Add the returned ui_document as a new assistant message
      const uiDocMessage: Message = {
        role: 'assistant',
        content: 'Action completed',
        timestamp: new Date(),
        metadata: { ui_document: result.ui_document as UIDocument },
      };
      setMessages(prev => [...prev, uiDocMessage]);
      if (addMessage) {
        addMessage(uiDocMessage);
      }
    }
  }, [submitAction, addMessage]);

  // Load chat history when session changes
  useEffect(() => {
    if (chatHistory?.messages) {
      setMessages(chatHistory.messages as Message[]);
    } else {
      setMessages([]);
    }
  }, [chatHistory]);

  const handleSendMessage = useCallback(async () => {
    if (!inputValue.trim() || isLoading) return;

    const userMessage: Message = {
      role: 'user',
      content: inputValue.trim(),
      timestamp: new Date(),
      metadata: { status: 'sent' },
    };

    setMessages(prev => [...prev, userMessage]);
    if (addMessage) {
      addMessage(userMessage);
    }
    setInputValue('');
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch('/api/v1/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          messages: [...messages, userMessage].map(({ role, content }) => ({ role, content })),
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error: ${response.status}`);
      }

      const data = await response.json();

      const assistantMessage: Message = {
        role: 'assistant',
        content: data.message?.content || 'No response',
        timestamp: new Date(),
        metadata: { status: 'delivered' },
      };

      setMessages(prev => [...prev, assistantMessage]);
      if (addMessage) {
        addMessage(assistantMessage);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send message');
      // Add error message bubble
      const errorMessage: Message = {
        role: 'assistant',
        content: 'Sorry, I encountered an error. Please try again.',
        timestamp: new Date(),
        metadata: { error: true },
      };
      setMessages(prev => [...prev, errorMessage]);
      if (addMessage) {
        addMessage(errorMessage);
      }
    } finally {
      setIsLoading(false);
    }
  }, [inputValue, messages, isLoading, addMessage]);

  return (
    <div className="chat-page">
      <ChatInterface loading={isLoading}>
        <div className="messages-container">
          {isLoading && messages.length === 0 ? (
            <div className="loading-state">
              <LoadingSpinner size="lg" />
              <p>Thinking...</p>
            </div>
          ) : messages.length === 0 ? (
            <div className="empty-state">
              <p>Start a conversation by typing a message below.</p>
            </div>
          ) : (
            messages.map((msg, index) => (
              <div key={index} className="message-wrapper">
                <MessageBubble
                  role={msg.role}
                  content={msg.content}
                  timestamp={msg.timestamp}
                  metadata={msg.metadata}
                />
                {msg.metadata?.ui_document && (
                  <UIDocumentRenderer ui_document={msg.metadata.ui_document} onAction={handleBlockAction} />
                )}
              </div>
            ))
          )}
        </div>
        {error && (
          <div className="error-container">
            <div className="error-message">{error}</div>
            <ActionButton
              label="Retry"
              onClick={handleSendMessage}
              variant="primary"
              disabled={!inputValue.trim() && messages.length > 0}
            />
          </div>
        )}
        <div className="input-container">
          <UserInput
            value={inputValue}
            onChange={setInputValue}
            placeholder="Type a message..."
            disabled={isLoading}
            onSubmit={handleSendMessage}
          />
          <ActionButton
            label="Send"
            onClick={handleSendMessage}
            variant="primary"
            loading={isLoading}
            disabled={!inputValue.trim()}
          />
        </div>
      </ChatInterface>
    </div>
  );
}

// Schema Page Component
function SchemaPage() {
  const [blocks, setBlocks] = useState<UIBlock[]>([]);
  const [selectedBlockId, setSelectedBlockId] = useState<string | undefined>();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchSchema = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/v1/ui-schema');
      if (!response.ok) {
        throw new Error(`HTTP error: ${response.status}`);
      }
      const data = await response.json();
      // Handle both array and object with blocks property
      setBlocks(Array.isArray(data) ? data : data.blocks || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch schema');
      // Use sample data for demo
      setBlocks([
        {
          id: 'sample-1',
          type: 'card',
          content: { title: 'Welcome Card', description: 'This is a sample UI block' },
          actions: [{ id: 'action-1', type: 'button', label: 'Get Started' }],
        },
        {
          id: 'sample-2',
          type: 'text',
          content: { title: 'Information', description: 'Sample text block content' },
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Fetch schema on mount
  React.useEffect(() => {
    fetchSchema();
  }, [fetchSchema]);

  return (
    <div className="schema-page">
      <div className="schema-header">
        <h1 className="schema-title">UI Schema Viewer</h1>
        <ActionButton
          label="Refresh"
          onClick={fetchSchema}
          variant="secondary"
          loading={isLoading}
        />
      </div>
      {error && <div className="error-message">{error}</div>}
      <UISchemaViewer
        blocks={blocks}
        selectedBlockId={selectedBlockId}
        onBlockSelect={(block) => setSelectedBlockId(block.id)}
      />
    </div>
  );
}

// Main App Component
export default function App() {
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Real-time collaboration state
  const [collaborationStatus, setCollaborationStatus] = useState({ isConnected: false, tabCount: 1 });
  const channelRef = useRef<BroadcastChannel | null>(null);
  const tabIdRef = useRef<string>(Date.now().toString());

  // Set up BroadcastChannel for cross-tab communication
  useEffect(() => {
    if (typeof BroadcastChannel === 'undefined') {
      return;
    }

    const channel = new BroadcastChannel('agui-collaboration');
    channelRef.current = channel;

    // Announce this tab is active
    channel.postMessage({ type: 'tab-active', tabId: tabIdRef.current, timestamp: Date.now() });

    channel.onmessage = (event) => {
      const data = event.data;
      if (data.type === 'tab-active' || data.type === 'tab-closed') {
        // Count active tabs periodically
        setCollaborationStatus(prev => ({
          ...prev,
          isConnected: true,
          tabCount: prev.tabCount,
        }));
      }
    };

    // Handle incoming messages to track tab count
    let activeTabs = new Set([tabIdRef.current]);
    channel.onmessage = (event) => {
      const data = event.data;
      if (data.type === 'tab-active' && data.tabId !== tabIdRef.current) {
        activeTabs.add(data.tabId);
      } else if (data.type === 'tab-closed' || data.type === 'tab-inactive') {
        activeTabs.delete(data.tabId);
      }
      setCollaborationStatus({
        isConnected: activeTabs.size > 0,
        tabCount: activeTabs.size,
      });
    };

    // Announce tab closing on unload
    const handleBeforeUnload = () => {
      channel.postMessage({ type: 'tab-closed', tabId: tabIdRef.current });
    };
    window.addEventListener('beforeunload', handleBeforeUnload);

    // Periodic heartbeat to maintain tab count
    const heartbeat = setInterval(() => {
      channel.postMessage({ type: 'tab-active', tabId: tabIdRef.current, timestamp: Date.now() });
    }, 5000);

    setCollaborationStatus({ isConnected: true, tabCount: 1 });

    return () => {
      channel.postMessage({ type: 'tab-closed', tabId: tabIdRef.current });
      channel.close();
      window.removeEventListener('beforeunload', handleBeforeUnload);
      clearInterval(heartbeat);
    };
  }, []);

  const {
    currentSession,
    sessions,
    createSession,
    switchSession,
    renameSession,
    deleteSession,
    addSession,
  } = useSession();

  const { chatHistory, addMessage, deleteHistoryForSession, allHistories } = useChatHistory(currentSession);

  // Export chat history as JSON
  const handleExportChatHistory = useCallback(() => {
    if (!currentSession) {
      alert('No current session to export.');
      return;
    }

    const dataToExport = allHistories[`history_${currentSession.id}`] || null;

    if (!dataToExport) {
      alert('No chat history to export for the current session.');
      return;
    }

    const sessionId = currentSession.id;
    const sessionName = currentSession.name;

    const exportData = {
      sessionId,
      sessionName,
      exportedAt: new Date().toISOString(),
      messages: dataToExport.messages.map(m => ({
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
  }, [currentSession, allHistories]);

  const handleNewSession = useCallback(() => {
    const newSession = createSession();
    addSession(newSession);
    setSidebarOpen(false);
  }, [createSession, addSession]);

  const handleSessionSelect = useCallback((session: typeof currentSession) => {
    if (session) {
      switchSession(session.id);
      setSidebarOpen(false);
    }
  }, [switchSession]);

  const handleDeleteSession = useCallback((sessionId: string) => {
    deleteSession(sessionId);
    deleteHistoryForSession(sessionId);
  }, [deleteSession, deleteHistoryForSession]);

  return (
    <div className="app">
      <HistorySidebar
        sessions={sessions}
        currentSession={currentSession}
        onSessionSelect={handleSessionSelect}
        onNewSession={handleNewSession}
        onDeleteSession={handleDeleteSession}
        onRenameSession={renameSession}
        onClose={() => setSidebarOpen(false)}
        isOpen={sidebarOpen}
      />
      <header className="app-header">
        <div className="header-left">
          <button
            className="menu-button"
            onClick={() => setSidebarOpen(true)}
            aria-label="Open history"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 12h18M3 6h18M3 18h18" />
            </svg>
          </button>
          <h1 className="app-title">AGUI Agent</h1>
          <SessionSelector
            currentSession={currentSession}
            onSessionSelect={handleSessionSelect}
            onNewSession={handleNewSession}
            sessions={sessions}
          />
        </div>
        <nav className="nav-links">
          <Link to="/">
            <ActionButton
              label="Chat"
              variant={location.pathname === '/' ? 'primary' : 'secondary'}
              onClick={() => {}}
            />
          </Link>
          <Link to="/schema">
            <ActionButton
              label="Schema"
              variant={location.pathname === '/schema' ? 'primary' : 'secondary'}
              onClick={() => {}}
            />
          </Link>
        </nav>
        <div className="header-right">
          <button
            className="export-button"
            onClick={handleExportChatHistory}
            title="Export chat history as JSON"
            aria-label="Export chat history"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3" />
            </svg>
          </button>
          <CollaborationStatus isConnected={collaborationStatus.isConnected} tabCount={collaborationStatus.tabCount} />
        </div>
      </header>
      <Routes>
        <Route path="/" element={<ChatPage chatHistory={chatHistory} addMessage={addMessage} />} />
        <Route path="/schema" element={<SchemaPage />} />
      </Routes>
    </div>
  );
}
