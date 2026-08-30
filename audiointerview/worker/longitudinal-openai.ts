import { openaiText } from './openai.js';
import type { RuntimeEnv } from './types.js';
import type {
  FinalizeSessionInput,
  MemoryEdge,
  MemoryNode,
  ParticipantProfile,
  SessionMemoryUpdate,
} from './longitudinal-types.js';
import { emptyProfile } from './longitudinal-types.js';

function transcript(input: FinalizeSessionInput) {
  return input.messages.map((message) => `[${message.id}] ${message.role}: ${message.content}`).join('\n');
}

function parseJsonObject(text: string): unknown {
  const trimmed = text.trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '');
  return JSON.parse(trimmed);
}

function strings(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string').map((item) => item.trim()).filter(Boolean) : [];
}

function profile(value: unknown): ParticipantProfile {
  const item = value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
  return {
    role: typeof item.role === 'string' ? item.role : null,
    years_of_experience: typeof item.years_of_experience === 'string' ? item.years_of_experience : null,
    typical_day: strings(item.typical_day),
    responsibilities: strings(item.responsibilities),
    collaborators: strings(item.collaborators),
  };
}

function nodes(value: unknown): MemoryNode[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((raw) => {
    if (!raw || typeof raw !== 'object') return [];
    const item = raw as Record<string, unknown>;
    if (typeof item.key !== 'string' || typeof item.text !== 'string' || typeof item.kind !== 'string') return [];
    return [{
      key: item.key,
      kind: item.kind as MemoryNode['kind'],
      text: item.text,
      status: (item.status as MemoryNode['status']) ?? 'observed',
      confidence: typeof item.confidence === 'number' ? item.confidence : 0.5,
      evidence_message_ids: strings(item.evidence_message_ids),
    }];
  });
}

function edges(value: unknown): MemoryEdge[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((raw) => {
    if (!raw || typeof raw !== 'object') return [];
    const item = raw as Record<string, unknown>;
    if (typeof item.from_key !== 'string' || typeof item.to_key !== 'string' || typeof item.relation !== 'string') return [];
    return [{
      from_key: item.from_key,
      to_key: item.to_key,
      relation: item.relation as MemoryEdge['relation'],
      explicitness: item.explicitness === 'explicit' ? 'explicit' : 'inferred',
      confidence: typeof item.confidence === 'number' ? item.confidence : 0.5,
      evidence_message_ids: strings(item.evidence_message_ids),
    }];
  });
}

export async function extractSessionMemory(env: RuntimeEnv, input: FinalizeSessionInput): Promise<SessionMemoryUpdate> {
  const prompt = `あなたは反復型インタビューの記憶整理エージェントです。
会話から、参加者本人が述べた内容だけを抽出してください。中心は「状況→調整行動→理由→判断基準→価値観→形成源」です。

規則:
- 想像で穴を埋めない。発言された関係だけ explicit とする。
- inferred は有用で控えめな仮説だけにし、status=hypothesis、confidence<=0.6 とする。
- ノードの key はこの出力内で一意な短い英数字にする。
- 各ノードとエッジに根拠の message id を付ける。
- プロフィールは役割、経験年数、一日の流れ、責任範囲、関係者だけを抽出する。不明値は null または空配列。
- summary は今回分だけを簡潔にまとめる。
- 過去情報は同定の参考にするが、今回の証拠として流用しない。
- JSONだけを返す。

出力形式:
{"summary":"...","profile_patch":{"role":null,"years_of_experience":null,"typical_day":[],"responsibilities":[],"collaborators":[]},"nodes":[{"key":"n1","kind":"adjustment","text":"...","status":"observed","confidence":0.9,"evidence_message_ids":["..."]}],"edges":[{"from_key":"n1","to_key":"n2","relation":"because_of","explicitness":"explicit","confidence":0.9,"evidence_message_ids":["..."]}]}

過去の参加者記憶:
${JSON.stringify(input.previousMemory)}

今回の会話:
${transcript(input)}`;

  try {
    const raw = parseJsonObject(await openaiText(env, prompt)) as Record<string, unknown>;
    return {
      summary: typeof raw.summary === 'string' ? raw.summary.trim() : '',
      profile_patch: profile(raw.profile_patch),
      nodes: nodes(raw.nodes),
      edges: edges(raw.edges),
    };
  } catch (error) {
    console.error('Failed to extract longitudinal memory', error);
    return { summary: '', profile_patch: emptyProfile(), nodes: [], edges: [] };
  }
}
