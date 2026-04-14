// Main Renderer component that renders UIDocument to interactive UI

import React = require("react");
import { ComponentRegistry, UIDocument, UIBlock, ActionModel, globalRegistry, registerBlock } from "./registry";
import { TextBlock } from "./TextBlock";
import { StatCard } from "./StatCard";
import { ActionCard } from "./ActionCard";
import { Section } from "./Section";
import { ListView } from "./ListView";
import { FormRenderer } from "./FormRenderer";

// Register default components
registerBlock("text", TextBlock);
registerBlock("stat", StatCard);
registerBlock("card", ActionCard);
registerBlock("section", Section);
registerBlock("list", ListView);
registerBlock("form", FormRenderer);

interface RendererProps {
  document: UIDocument;
  registry?: ComponentRegistry;
  onAction?: (action: ActionModel) => void;
}

export function Renderer({ document, registry = globalRegistry, onAction }: RendererProps): React.ReactElement {
  return (
    <div className="renderer-container" data-document-id={document.id}>
      {document.title && (
        <header className="document-header">
          <h1 className="document-title">{document.title}</h1>
        </header>
      )}
      <main className="document-blocks">
        {document.blocks.map((block) => (
          <React.Fragment key={block.id}>
            {renderBlockWithRegistry(block, registry, onAction)}
          </React.Fragment>
        ))}
      </main>
    </div>
  );
}

function renderBlockWithRegistry(
  block: UIBlock,
  registry: ComponentRegistry,
  onAction?: (action: ActionModel) => void
): React.ReactElement | null {
  const Component = registry.get(block.type);
  if (!Component) {
    return (
      <div className="block-unknown" key={block.id}>
        Unknown block type: {block.type}
      </div>
    );
  }
  return <Component key={block.id} block={block} onAction={onAction} />;
}

// Export the renderer with default registry
export { globalRegistry as defaultRegistry };