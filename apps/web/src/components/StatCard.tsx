// StatCard component for displaying statistics

import React = require("react");

interface StatCardProps {
  block: {
    content: {
      label?: string;
      value?: string | number;
      trend?: "up" | "down" | "neutral";
      trend_value?: string;
    };
    metadata?: {
      format?: "number" | "currency" | "percentage";
    };
  };
}

export function StatCard({ block }: StatCardProps): React.ReactElement {
  const { content } = block;
  const trendIcon = content.trend === "up" ? "↑" : content.trend === "down" ? "↓" : "";

  return (
    <div className="block block-stat" data-block-type="stat">
      <span className="stat-label">{content.label}</span>
      <span className="stat-value">{content.value}</span>
      {content.trend && (
        <span className={`stat-trend trend-${content.trend}`}>
          {trendIcon} {content.trend_value}
        </span>
      )}
    </div>
  );
}