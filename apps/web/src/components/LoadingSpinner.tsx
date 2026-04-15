// LoadingSpinner - Neumorphic loading spinner component

import React from 'react';

interface LoadingSpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

export function LoadingSpinner({
  size = 'md',
  className = '',
}: LoadingSpinnerProps): React.ReactElement {
  const sizeClass = `spinner-${size}`;

  return (
    <div
      className={`loading-spinner-container ${sizeClass} ${className}`.trim()}
      role="status"
      aria-label="Loading"
    >
      <div className="neu-spinner" />
      <span className="sr-only">Loading...</span>
    </div>
  );
}

export default LoadingSpinner;
