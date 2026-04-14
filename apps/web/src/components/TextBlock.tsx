// TextBlock component for rendering text content

import React = require("react");

interface TextBlockProps {
  block: {
    content: {
      text?: string;
      format?: "plain" | "markdown" | "html";
    };
  };
}

export function TextBlock({ block }: TextBlockProps): React.ReactElement {
  const { content } = block;
  const format = content.format || "plain";

  const renderText = () => {
    switch (format) {
      case "markdown":
        return <span className="text-markdown">{content.text}</span>;
      case "html":
        return <span dangerouslySetInnerHTML={{ __html: content.text }} />;
      default:
        return <span className="text-plain">{content.text}</span>;
    }
  };

  return (
    <div className="block block-text" data-block-type="text">
      {renderText()}
    </div>
  );
}