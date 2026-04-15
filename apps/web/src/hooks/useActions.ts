// useActions - React hook for handling form actions submission

import { useState, useCallback } from 'react';

export interface ActionParams {
  [key: string]: unknown;
}

export interface ActionResult {
  success: boolean;
  result?: unknown;
  error?: string;
  ui_document?: unknown;
}

export function useActions() {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submitAction = useCallback(async (
    actionId: string,
    params: ActionParams = {},
    sessionId?: string
  ): Promise<ActionResult | null> => {
    setIsSubmitting(true);
    setError(null);

    try {
      const response = await fetch('/api/v1/actions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          action_id: actionId,
          params,
          session_id: sessionId,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error: ${response.status}`);
      }

      const data = await response.json();
      return {
        success: data.success,
        result: data.result,
        error: data.error,
        ui_document: data.ui_document,
      };
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to submit action';
      setError(errorMessage);
      return {
        success: false,
        error: errorMessage,
      };
    } finally {
      setIsSubmitting(false);
    }
  }, []);

  return {
    submitAction,
    isSubmitting,
    error,
    clearError: () => setError(null),
  };
}

export default useActions;