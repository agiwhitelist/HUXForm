// UISchemaViewer - Display block types in card format

import React from "react";

interface UIBlock {
  id: string;
  type: string;
  content: Record<string, unknown>;
  actions?: Array<{
    id: string;
    type: "button" | "link" | "submit" | "navigate";
    label: string;
    disabled?: boolean;
    icon?: string;
  }>;
  metadata?: Record<string, unknown>;
}

interface UISchemaViewerProps {
  blocks: UIBlock[];
  onBlockSelect?: (block: UIBlock) => void;
  selectedBlockId?: string;
}

export function UISchemaViewer({
  blocks,
  onBlockSelect,
  selectedBlockId,
}: UISchemaViewerProps): React.ReactElement {
  const handleCardClick = (block: UIBlock): void => {
    onBlockSelect?.(block);
  };

  const handleKeyDown = (e: React.KeyboardEvent, block: UIBlock): void => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onBlockSelect?.(block);
    }
  };

  return (
    <div className="ui-schema-viewer" role="list" aria-label="UI blocks">
      {blocks.map((block) => {
        const isSelected = block.id === selectedBlockId;
        const isDisabled = block.metadata?.disabled === true;

        return (
          <div
            key={block.id}
            className={`ui-schema-card ${isSelected ? "selected" : ""} ${isDisabled ? "disabled" : ""}`.trim()}
            onClick={(): void => { if (!isDisabled) handleCardClick(block); }}
            onKeyDown={(e): void => { if (!isDisabled) handleKeyDown(e, block); }}
            role="listitem"
            aria-selected={isSelected}
            aria-disabled={isDisabled}
            tabIndex={isDisabled ? -1 : 0}
          >
            <div className="ui-schema-card-title">
              {(block.content.title as string) || block.id}
            </div>
            <div className="ui-schema-card-type">{block.type}</div>
            {block.content.description ? (
              <div className="ui-schema-card-description">
                {String(block.content.description)}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export default UISchemaViewer;