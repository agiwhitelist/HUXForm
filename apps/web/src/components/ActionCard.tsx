// ActionCard component for card with actions

import React = require("react");

interface ActionCardProps {
  block: {
    content: {
      title?: string;
      description?: string;
      items?: Array<{ label: string; value: string }>;
    };
    actions?: Array<{
      id: string;
      type: "button" | "link" | "submit" | "navigate";
      label: string;
      disabled?: boolean;
      icon?: string;
    }>;
    metadata?: {
      variant?: "default" | "elevated" | "outlined";
    };
  };
  onAction?: (action: { id: string }) => void;
}

export function ActionCard({ block, onAction }: ActionCardProps): React.ReactElement {
  const { content, actions = [] } = block;
  const variant = block.metadata?.variant || "default";

  return (
    <div className={`block block-card variant-${variant}`} data-block-type="card">
      {content.title && <h3 className="card-title">{content.title}</h3>}
      {content.description && <p className="card-description">{content.description}</p>}
      {content.items && content.items.length > 0 && (
        <ul className="card-items">
          {content.items.map((item, i) => (
            <li key={i}>
              <span className="item-label">{item.label}</span>
              <span className="item-value">{item.value}</span>
            </li>
          ))}
        </ul>
      )}
      {actions.length > 0 && (
        <div className="card-actions">
          {actions.map((action) => (
            <button
              key={action.id}
              className={`action-btn action-btn-${action.type}`}
              disabled={action.disabled}
              onClick={() => onAction?.({ id: action.id })}
            >
              {action.icon && <span className="action-icon">{action.icon}</span>}
              {action.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}