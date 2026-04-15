// MessageBubble - Differentiated bubbles for user vs assistant messages

import React from "react";

interface MessageBubbleProps {
  role: "user" | "assistant" | "system";
  content: string;
  timestamp?: Date;
  metadata?: {
    status?: "sent" | "delivered" | "read";
    error?: boolean;
  };
}

function formatTimestamp(date?: Date): string {
  if (!date) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function MessageBubble({
  role,
  content,
  timestamp,
  metadata,
}: MessageBubbleProps): React.ReactElement {
  const statusClass = metadata?.status ? `status-${metadata.status}` : "";
  const errorClass = metadata?.error ? "error" : "";

  return (
    <div
      className={`message-bubble ${role} ${statusClass} ${errorClass}`.trim()}
      role="article"
      aria-label={`${role} message`}
      data-role={role}
    >
      <div className="message-content">{content}</div>
      {timestamp && (
        <div className="message-timestamp">
          {metadata?.status && (
            <span className={`status-indicator ${metadata.status}`} aria-hidden="true" />
          )}
          {formatTimestamp(timestamp)}
        </div>
      )}
    </div>
  );
}

export default MessageBubble;