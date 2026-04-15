// ChatInterface - Main container with neumorphic inset effect

import React from "react";

interface ChatInterfaceProps {
  children: React.ReactNode;
  className?: string;
  loading?: boolean;
}

export function ChatInterface({
  children,
  className = "",
  loading = false,
}: ChatInterfaceProps): React.ReactElement {
  return (
    <div
      className={`chat-interface ${loading ? "loading" : ""} ${className}`.trim()}
      role="main"
      aria-label="Chat interface"
    >
      {children}
    </div>
  );
}

export default ChatInterface;