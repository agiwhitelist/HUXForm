// FormRenderer component for forms

import React = require("react");

interface FormRendererProps {
  block: {
    content: {
      fields?: Array<{
        name: string;
        type: "text" | "number" | "email" | "password" | "select" | "checkbox";
        label?: string;
        placeholder?: string;
        options?: string[];
        required?: boolean;
      }>;
    };
    actions?: Array<{
      id: string;
      type: "submit" | "button";
      label: string;
      disabled?: boolean;
    }>;
    metadata?: {
      layout?: "vertical" | "horizontal";
    };
  };
  onAction?: (action: { id: string; params?: Record<string, unknown> }) => void;
}

export function FormRenderer({ block, onAction }: FormRendererProps): React.ReactElement {
  const { content, actions = [] } = block;
  const layout = block.metadata?.layout || "vertical";

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const formData = new FormData(e.target as HTMLFormElement);
    const data: Record<string, unknown> = {};
    formData.forEach((value, key) => {
      data[key] = value;
    });
    onAction?.({ id: "submit", params: data });
  };

  return (
    <div className="block block-form" data-block-type="form">
      <form className={`form-layout-${layout}`} onSubmit={handleSubmit}>
        {content.fields?.map((field) => (
          <div key={field.name} className="form-field">
            {field.label && (
              <label htmlFor={field.name} className="field-label">
                {field.label}
                {field.required && <span className="required">*</span>}
              </label>
            )}
            {field.type === "select" ? (
              <select
                id={field.name}
                name={field.name}
                required={field.required}
                className="field-input"
              >
                {field.placeholder && (
                  <option value="">{field.placeholder}</option>
                )}
                {field.options?.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            ) : field.type === "checkbox" ? (
              <input
                type="checkbox"
                id={field.name}
                name={field.name}
                required={field.required}
                className="field-checkbox"
              />
            ) : (
              <input
                type={field.type}
                id={field.name}
                name={field.name}
                placeholder={field.placeholder}
                required={field.required}
                className="field-input"
              />
            )}
          </div>
        ))}
        {actions.length > 0 && (
          <div className="form-actions">
            {actions.map((action) => (
              <button
                key={action.id}
                type={action.type === "submit" ? "submit" : "button"}
                disabled={action.disabled}
                className="form-action-btn"
                onClick={() => action.type !== "submit" && onAction?.({ id: action.id })}
              >
                {action.label}
              </button>
            ))}
          </div>
        )}
      </form>
    </div>
  );
}