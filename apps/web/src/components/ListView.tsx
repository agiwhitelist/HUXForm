// ListView component for rendering lists

import React = require("react");

interface ListViewProps {
  block: {
    content: {
      items?: Array<{ id: string; label: string; description?: string; icon?: string }>;
      ordered?: boolean;
    };
  };
}

export function ListView({ block }: ListViewProps): React.ReactElement {
  const { content } = block;
  const Tag = content.ordered ? "ol" : "ul";

  return (
    <div className="block block-list" data-block-type="list">
      <Tag className="list-items">
        {content.items?.map((item) => (
          <li key={item.id} className="list-item">
            {item.icon && <span className="item-icon">{item.icon}</span>}
            <span className="item-label">{item.label}</span>
            {item.description && (
              <span className="item-description">{item.description}</span>
            )}
          </li>
        ))}
      </Tag>
    </div>
  );
}