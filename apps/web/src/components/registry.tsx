// UI Renderer - React Component Registry

export type BlockType =
  | "text"
  | "stat"
  | "card"
  | "section"
  | "list"
  | "table"
  | "chart"
  | "form"
  | "selector"
  | "timeline"
  | "image"
  | "action_bar";

export type ActionType = "button" | "link" | "submit" | "navigate";

export interface ActionModel {
  id: string;
  type: ActionType;
  label: string;
  handler?: string;
  params?: Record<string, unknown>;
  disabled?: boolean;
  icon?: string;
}

export interface UIBlock {
  id: string;
  type: BlockType;
  content: Record<string, unknown>;
  actions: ActionModel[];
  metadata?: Record<string, unknown>;
}

export interface UIDocument {
  version: string;
  id?: string;
  title?: string;
  blocks: UIBlock[];
  metadata?: Record<string, unknown>;
}

export interface ComponentProps {
  block: UIBlock;
  onAction?: (action: ActionModel) => void;
}

// Component registry type
export interface UIComponent {
  type: BlockType;
  component: React.ComponentType<ComponentProps>;
}

// Registry for mapping block types to components
export class ComponentRegistry {
  private registry: Map<BlockType, React.ComponentType<ComponentProps>> = new Map();

  register(type: BlockType, component: React.ComponentType<ComponentProps>): void {
    this.registry.set(type, component);
  }

  get(type: BlockType): React.ComponentType<ComponentProps> | undefined {
    return this.registry.get(type);
  }

  has(type: BlockType): boolean {
    return this.registry.has(type);
  }

  renderBlock(block: UIBlock, onAction?: (action: ActionModel) => void): React.ReactElement | null {
    const Component = this.registry.get(block.type);
    if (!Component) {
      console.warn(`No component registered for block type: ${block.type}`);
      return null;
    }
    return <Component block={block} onAction={onAction} />;
  }
}

// Singleton registry instance
export const globalRegistry = new ComponentRegistry();

// Registry helper functions
export function registerBlock(
  type: BlockType,
  component: React.ComponentType<ComponentProps>
): void {
  globalRegistry.register(type, component);
}

export function renderDocument(
  doc: UIDocument,
  registry: ComponentRegistry = globalRegistry,
  onAction?: (action: ActionModel) => void
): React.ReactElement {
  return (
    <div className="uidocument" data-document-id={doc.id}>
      {doc.title && <h1 className="document-title">{doc.title}</h1>}
      {doc.blocks.map((block) => (
        <React.Fragment key={block.id}>
          {registry.renderBlock(block, onAction)}
        </React.Fragment>
      ))}
    </div>
  );
}

// Export React for JSX
import React = require("react");