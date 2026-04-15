// UIDocumentRenderer - Renders ui_document blocks within chat messages

import React from "react";
import { UIDocument, renderDocument, globalRegistry } from "./registry";

interface UIDocumentRendererProps {
  ui_document: UIDocument;
  onAction?: (action: { id: string; type: string; label: string; params?: Record<string, unknown> }) => void;
}

export function UIDocumentRenderer({ ui_document, onAction }: UIDocumentRendererProps): React.ReactElement {
  const handleAction = (action: { id: string; type: string; label: string; params?: Record<string, unknown> }) => {
    onAction?.(action);
  };

  return (
    <div className="ui-document-renderer">
      {renderDocument(ui_document, globalRegistry, handleAction)}
    </div>
  );
}