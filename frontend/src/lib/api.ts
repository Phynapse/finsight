/**
 * Typed API client for the FinSight backend.
 */

import type {
  Capabilities,
  DatasetSummary,
  HealthResponse,
  QuestionAnswer,
} from './types';

const BASE = '/api/v1';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  const body = await response.json();
  if (!response.ok) {
    const message = body?.error?.message ?? `HTTP ${response.status}`;
    throw new Error(message);
  }
  return body as T;
}

export const api = {
  health(): Promise<HealthResponse> {
    return request('/health');
  },

  capabilities(): Promise<Capabilities> {
    return request('/capabilities');
  },

  datasets(): Promise<{ datasets: DatasetSummary[] }> {
    return request('/datasets');
  },

  ask(question: string): Promise<QuestionAnswer> {
    return request('/questions', {
      method: 'POST',
      body: JSON.stringify({ question }),
    });
  },
};