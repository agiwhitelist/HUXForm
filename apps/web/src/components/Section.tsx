// Section component for grouping blocks

import React = require("react");

interface SectionProps {
  block: {
    content: {
      title?: string;
      level?: number;
    };
  };
}

export function Section({ block }: SectionProps): React.ReactElement {
  const { content } = block;
  const level = content.level || 2;
  const Tag = `h${level}` as keyof JSX.IntrinsicElements;

  return (
    <div className="block block-section" data-block-type="section">
      {content.title && <Tag className="section-title">{content.title}</Tag>}
    </div>
  );
}