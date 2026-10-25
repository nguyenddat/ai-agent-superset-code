import { agentDefinitionsApi, agentQuestionsApi, requestJson } from './api';
import { semanticLayerEvents } from './constants';
import type { SemanticLayerModule } from './constants';
import type { AgentDefinitionKind, AgentReviewQuestion } from './types';

/** Add the metric a question is missing: the metrics module shows the proposal next to its list. */
export type MetricRequest = { kind: 'metric'; question: AgentReviewQuestion };

/**
 * Cover a concept users defined for themselves with a shared term or rule. Only the name and concept are carried over:
 * the shared definition and its threshold are the business experts' call, not a copy of what users chose.
 */
export type ConceptRequest = {
  kind: AgentDefinitionKind;
  name: string;
  concept: string | null;
  definitionIds: number[];
  userCount: number;
  exampleQuestion: string | null;
};

export type CreationRequest = MetricRequest | ConceptRequest;

const MODULE_BY_KIND: Record<CreationRequest['kind'], SemanticLayerModule> = {
  glossary: 'glossary',
  metric: 'metrics',
  expert_rule: 'rules',
};

let pendingRequest: CreationRequest | null = null;

export function requestCreation(request: CreationRequest) {
  pendingRequest = request;
  window.dispatchEvent(new CustomEvent(semanticLayerEvents.moduleRequest, { detail: MODULE_BY_KIND[request.kind] }));
}

/** Saving a term or rule from users' definitions marks those definitions as covered by a shared definition. */
export async function completeConceptCreation(request: ConceptRequest) {
  try {
    await requestJson(agentDefinitionsApi.review, 'PUT', { ids: request.definitionIds, status: 'promoted' });
  } catch {
    // The definitions stay "Chưa xem" and can still be marked from the review page.
  }
}

/** Saving the proposed metric resolves its question when the metric was the only missing piece. */
export async function completeMetricCreation(request: MetricRequest) {
  if (request.question.missing.length !== 1) return;
  try {
    await requestJson(agentQuestionsApi.handling(request.question.id), 'PUT', { status: 'created' });
  } catch {
    // The question keeps "Đang tạo mới" and can still be completed from the review page.
  }
}

/** The request waiting for this module, handed out once so revisiting the module later opens it normally. */
export function takeMetricRequest(): MetricRequest | null {
  if (pendingRequest?.kind !== 'metric') return null;
  const request = pendingRequest;
  pendingRequest = null;
  return request;
}

export function takeConceptRequest(kind: AgentDefinitionKind): ConceptRequest | null {
  if (pendingRequest?.kind !== kind) return null;
  const request = pendingRequest;
  pendingRequest = null;
  return request;
}
