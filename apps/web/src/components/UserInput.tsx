// UserInput - Text input field with embossed effect

import React from "react";

interface UserInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  maxLength?: number;
  onSubmit?: () => void;
}

export function UserInput({
  value,
  onChange,
  placeholder = "Type a message...",
  disabled = false,
  maxLength,
  onSubmit,
}: UserInputProps): React.ReactElement {
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>): void => {
    if (e.key === "Enter" && !e.shiftKey && onSubmit) {
      e.preventDefault();
      onSubmit();
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>): void => {
    onChange(e.target.value);
  };

  return (
    <div className="user-input-wrapper" role="form" aria-label="Message input">
      <textarea
        className="user-input"
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={disabled}
        maxLength={maxLength}
        rows={1}
        aria-label="Message text"
        aria-multiline="true"
      />
    </div>
  );
}

export default UserInput;