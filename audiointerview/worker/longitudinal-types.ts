import type { Language, MessageRow } from './types.js';

export type MemoryKind =
  | 'profile'
  | 'situation'
  | 'adjustment'
  | 'reason'
  | 'criterion'
  | 'value'
  | 'source'
  | 'personal_meaning';

export type MemoryStatus = 'observed' | 'hypothesis' | 'confirmed' | 'contradicted' | 'superseded';

export interface ParticipantProfile {
  role: string | null;
  years_of_experience: string | null;
  typical_day: string[];
  responsibilities: string[];
  collaborators: string[];
}

export interface MemoryNode {
  key: string;
  kind: MemoryKind;
  text: string;
  status: MemoryStatus;
  confidence: number;
  evidence_message_ids: string[];
}

export interface MemoryEdge {
  from_key: string;
  to_key: string;
  relation: 'applies_when' | 'because_of' | 'guided_by' | 'motivated_by' | 'formed_by' | 'changed_from';
  explicitness: 'explicit' | 'inferred';
  confidence: number;
  evidence_message_ids: string[];
}

export interface SessionMemoryUpdate {
  summary: string;
  profile_patch: ParticipantProfile;
  nodes: MemoryNode[];
  edges: MemoryEdge[];
}

export interface StoredMemoryNode extends MemoryNode {
  id: string;
  first_session_id: string;
  last_session_id: string;
}

export interface StoredMemoryEdge extends MemoryEdge {
  id: string;
  from_node_id: string;
  to_node_id: string;
  first_session_id: string;
  last_session_id: string;
}

export interface ParticipantMemory {
  account_id: string;
  session_count: number;
  profile: ParticipantProfile;
  recent_summaries: Array<{ session_id: string; summary: string; ended_at: string }>;
  nodes: StoredMemoryNode[];
  edges: StoredMemoryEdge[];
}

export interface ContextualMemory {
  profile: ParticipantProfile;
  summaries: ParticipantMemory['recent_summaries'];
  nodes: StoredMemoryNode[];
  edges: StoredMemoryEdge[];
}

export interface StarterInput {
  accountId: string;
  language: Language;
  sessionCount: number;
  recentStarters: string[];
  profile: ParticipantProfile;
}

export interface FinalizeSessionInput {
  accountId: string;
  sessionId: string;
  language: Language;
  messages: MessageRow[];
  previousMemory: ParticipantMemory;
}

export const emptyProfile = (): ParticipantProfile => ({
  role: null,
  years_of_experience: null,
  typical_day: [],
  responsibilities: [],
  collaborators: [],
});
