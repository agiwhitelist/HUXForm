// ActionButton - Raised button with press animation

import React from "react";

interface ActionButtonProps {
  label: string;
  onClick: () => void;
  variant?: "primary" | "secondary" | "ghost";
  size?: "sm" | "md" | "lg";
  disabled?: boolean;
  loading?: boolean;
  icon?: React.ReactNode;
  type?: "button" | "submit" | "reset";
}

export function ActionButton({
  label,
  onClick,
  variant = "secondary",
  size = "md",
  disabled = false,
  loading = false,
  icon,
  type = "button",
}: ActionButtonProps): React.ReactElement {
  const isDisabled = disabled || loading;

  return (
    <button
      type={type}
      className={`action-button ${variant} ${size} ${loading ? "loading" : ""}`.trim()}
      onClick={onClick}
      disabled={isDisabled}
      aria-label={label}
      aria-busy={loading}
    >
      {loading ? (
        <span className="spinner" aria-hidden="true" />
      ) : (
        <>
          {icon && <span className="action-icon" aria-hidden="true">{icon}</span>}
          <span className="action-label">{label}</span>
        </>
      )}
    </button>
  );
}

export default ActionButton;