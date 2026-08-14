import { openaiText } from './openai.js';
import { nowIso, randomId } from './db.js';
import type {
  ExtractedInfo,
  InterviewState,
  Language,
  LongTermMemory,
  LongTermMemoryType,
  ProfileUpdateCandidate,
  RuntimeEnv,
  SessionSummary,
  WorkerContext,
  WorkerProfile,
} from './types.js';

type ProfileRow = {
  worker_id: string;
  role: string | null;
  department: string | null;
  total_experience_years: number | null;
  current_role_experience_years: number | null;
  assigned_processes_json: string;
  assigned_equipment_json: string;
  responsibilities_json: string;
  qualifications_json: string;
  expertise_json: string;
  education_experience_json: string;
  evidence_json: string;
  updated_at: string;
};

type MemoryRow = {
  id: string;
  worker_id: string;
  type: LongTermMemoryType;
  content: string;
  source_session_id: string | null;
  evidence_message_id: string | null;
  confidence: number;
  status: 'active' | 'resolved' | 'superseded';
  created_at: string;
};

type SummaryRow = {
  session_id: string;
  worker_id: string;
  summary: string;
  topics_json: string;
  unresolved_topics_json: string;
  final_state_json: string;
  created_at: string;
};

type ProfileCandidate = ProfileUpdateCandidate;

const profileStarters: Record<Language, string> = {
  ja: 'まず、普段はどんなお仕事をされているのか教えていただけますか？',
  en: 'To begin, could you tell me what kind of work you usually do?',
  de: 'Erzählen Sie mir zu Beginn bitte, welche Arbeit Sie normalerweise machen.',
};

const interviewTransitions: Record<Language, string> = {
  ja: 'ありがとうございます。お仕事の背景が少し見えてきました。最近担当された業務について、その時の状況も含めて教えていただけますか？',
  en: 'Thank you. I have a better sense of your background now. Could you tell me about a task you handled recently, including the situation?',
  de: 'Vielen Dank. Ich kann Ihren Hintergrund nun besser einordnen. Erzählen Sie bitte von einer Aufgabe, die Sie kürzlich übernommen haben, einschließlich der Situation.',
};

export function profileOpening(language: Language) {
  return profileStarters[language];
}

export function interviewTransition(language: Language) {
  return interviewTransitions[language];
}

function emptyProfile(workerId: string): WorkerProfile {
  return {
    workerId,
    role: null,
    department: null,
    totalExperienceYears: null,
    currentRoleExperienceYears: null,
    assignedProcesses: [],
    assignedEquipment: [],
    responsibilities: [],
    qualifications: [],
    expertise: [],
    educationExperience: [],
    updatedAt: null,
  };
}

function parseArray(value: string) {
  try {
    const parsed = JSON.parse(value) as unknown;
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : [];
  } catch {
    return [];
  }
}

function mapProfile(row: ProfileRow): WorkerProfile {
  return {
    workerId: row.worker_id,
    role: row.role,
    department: row.department,
    totalExperienceYears: row.total_experience_years,
    currentRoleExperienceYears: row.current_role_experience_years,
    assignedProcesses: parseArray(row.assigned_processes_json),
    assignedEquipment: parseArray(row.assigned_equipment_json),
    responsibilities: parseArray(row.responsibilities_json),
    qualifications: parseArray(row.qualifications_json),
    expertise: parseArray(row.expertise_json),
    educationExperience: parseArray(row.education_experience_json),
    updatedAt: row.updated_at,
  };
}

export async function getWorkerProfile(env: RuntimeEnv, workerId: string) {
  const row = await env.RI_db.prepare('SELECT * FROM worker_profiles WHERE worker_id = ?').bind(workerId).first<ProfileRow>();
  return row ? mapProfile(row) : emptyProfile(workerId);
}

export function needsProfileBuilding(profile: WorkerProfile) {
  return missingRequiredProfileFields(profile).length > 0;
}

export function missingRequiredProfileFields(profile: WorkerProfile) {
  const missing: string[] = [];
  if (!profile.role) missing.push('現在の役割');
  if (profile.totalExperienceYears === null) missing.push('総経験年数');
  if (profile.currentRoleExperienceYears === null) missing.push('現在業務の経験年数');
  if (!profile.assignedProcesses.length) missing.push('担当工程');
  if (!profile.assignedEquipment.length) missing.push('担当設備');
  if (!profile.responsibilities.length) missing.push('担当業務');
  return missing;
}

function mapMemory(row: MemoryRow): LongTermMemory {
  return {
    id: row.id,
    workerId: row.worker_id,
    type: row.type,
    content: row.content,
    sourceSessionId: row.source_session_id,
    evidenceMessageId: row.evidence_message_id,
    confidence: row.confidence,
    status: row.status,
    createdAt: row.created_at,
  };
}

function mapSummary(row: SummaryRow): SessionSummary {
  return {
    sessionId: row.session_id,
    workerId: row.worker_id,
    summary: row.summary,
    topics: parseArray(row.topics_json),
    unresolvedTopics: parseArray(row.unresolved_topics_json),
    finalState: JSON.parse(row.final_state_json) as InterviewState,
    createdAt: row.created_at,
  };
}

export async function getWorkerContext(env: RuntimeEnv, workerId: string): Promise<WorkerContext> {
  const [profile, memoryResult, summaryResult] = await Promise.all([
    getWorkerProfile(env, workerId),
    env.RI_db.prepare("SELECT * FROM long_term_memories WHERE worker_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT 30")
      .bind(workerId).all<MemoryRow>(),
    env.RI_db.prepare('SELECT * FROM session_summaries WHERE worker_id = ? ORDER BY created_at DESC LIMIT 5')
      .bind(workerId).all<SummaryRow>(),
  ]);
  return {
    profile,
    memories: memoryResult.results.map(mapMemory),
    recentSessionSummaries: summaryResult.results.map(mapSummary),
  };
}

function cleanCandidate(value: unknown): ProfileCandidate {
  const source = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  const array = (key: string) => Array.isArray(source[key]) ? (source[key] as unknown[]).filter((item): item is string => typeof item === 'string' && Boolean(item.trim())) : [];
  const text = (key: string) => typeof source[key] === 'string' && (source[key] as string).trim() ? (source[key] as string).trim() : null;
  const number = (key: string) => typeof source[key] === 'number' && Number.isFinite(source[key]) ? source[key] as number : null;
  return {
    role: text('role'),
    department: text('department'),
    totalExperienceYears: number('totalExperienceYears'),
    currentRoleExperienceYears: number('currentRoleExperienceYears'),
    assignedProcesses: array('assignedProcesses'),
    assignedEquipment: array('assignedEquipment'),
    responsibilities: array('responsibilities'),
    qualifications: array('qualifications'),
    expertise: array('expertise'),
    educationExperience: array('educationExperience'),
  };
}

function parseJsonObject(text: string) {
  try {
    return JSON.parse(text.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '')) as unknown;
  } catch {
    return {};
  }
}

export async function extractAndUpdateProfile(
  env: RuntimeEnv,
  workerId: string,
  userText: string,
  evidenceMessageId: string,
) {
  const existing = await getWorkerProfile(env, workerId);
  let candidate = cleanCandidate({});
  try {
    const result = await openaiText(env, `作業員プロフィールの更新候補をJSONで抽出してください。
最新の本人発話に明示された情報だけを使い、推測や既存情報からの補完を禁止します。
言及がないスカラーはnull、配列は[]にしてください。年数は数値にしてください。
キー: role, department, totalExperienceYears, currentRoleExperienceYears, assignedProcesses, assignedEquipment, responsibilities, qualifications, expertise, educationExperience

既存プロフィール:
${JSON.stringify(existing)}

最新の本人発話:
${userText}`);
    candidate = cleanCandidate(parseJsonObject(result));
  } catch (error) {
    console.error('Profile extraction failed', error);
  }

  const union = (current: string[], additions: string[]) => [...new Set([...current, ...additions].map((item) => item.trim()).filter(Boolean))].slice(-30);
  const updated: WorkerProfile = {
    ...existing,
    role: candidate.role ?? existing.role,
    department: candidate.department ?? existing.department,
    totalExperienceYears: candidate.totalExperienceYears ?? existing.totalExperienceYears,
    currentRoleExperienceYears: candidate.currentRoleExperienceYears ?? existing.currentRoleExperienceYears,
    assignedProcesses: union(existing.assignedProcesses, candidate.assignedProcesses),
    assignedEquipment: union(existing.assignedEquipment, candidate.assignedEquipment),
    responsibilities: union(existing.responsibilities, candidate.responsibilities),
    qualifications: union(existing.qualifications, candidate.qualifications),
    expertise: union(existing.expertise, candidate.expertise),
    educationExperience: union(existing.educationExperience, candidate.educationExperience),
    updatedAt: nowIso(),
  };
  const evidence = Object.fromEntries(Object.entries(candidate).filter(([, value]) => value !== null && (!Array.isArray(value) || value.length)).map(([key]) => [key, evidenceMessageId]));
  await env.RI_db.prepare(
    `INSERT INTO worker_profiles (
       worker_id, role, department, total_experience_years, current_role_experience_years,
       assigned_processes_json, assigned_equipment_json, responsibilities_json,
       qualifications_json, expertise_json, education_experience_json, evidence_json, updated_at
     ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(worker_id) DO UPDATE SET
       role=excluded.role, department=excluded.department,
       total_experience_years=excluded.total_experience_years,
       current_role_experience_years=excluded.current_role_experience_years,
       assigned_processes_json=excluded.assigned_processes_json,
       assigned_equipment_json=excluded.assigned_equipment_json,
       responsibilities_json=excluded.responsibilities_json,
       qualifications_json=excluded.qualifications_json,
       expertise_json=excluded.expertise_json,
       education_experience_json=excluded.education_experience_json,
       evidence_json=json_patch(worker_profiles.evidence_json, excluded.evidence_json),
       updated_at=excluded.updated_at`,
  ).bind(
    workerId, updated.role, updated.department, updated.totalExperienceYears, updated.currentRoleExperienceYears,
    JSON.stringify(updated.assignedProcesses), JSON.stringify(updated.assignedEquipment), JSON.stringify(updated.responsibilities),
    JSON.stringify(updated.qualifications), JSON.stringify(updated.expertise), JSON.stringify(updated.educationExperience),
    JSON.stringify(evidence), updated.updatedAt,
  ).run();
  return updated;
}

export async function applyProfileUpdate(
  env: RuntimeEnv,
  workerId: string,
  candidateValue: ProfileUpdateCandidate,
  evidenceMessageId: string,
) {
  const existing = await getWorkerProfile(env, workerId);
  const candidate = cleanCandidate(candidateValue);
  const union = (current: string[], additions: string[]) => [...new Set([...current, ...additions].map((item) => item.trim()).filter(Boolean))].slice(-30);
  const updated: WorkerProfile = {
    ...existing,
    role: candidate.role ?? existing.role,
    department: candidate.department ?? existing.department,
    totalExperienceYears: candidate.totalExperienceYears ?? existing.totalExperienceYears,
    currentRoleExperienceYears: candidate.currentRoleExperienceYears ?? existing.currentRoleExperienceYears,
    assignedProcesses: union(existing.assignedProcesses, candidate.assignedProcesses),
    assignedEquipment: union(existing.assignedEquipment, candidate.assignedEquipment),
    responsibilities: union(existing.responsibilities, candidate.responsibilities),
    qualifications: union(existing.qualifications, candidate.qualifications),
    expertise: union(existing.expertise, candidate.expertise),
    educationExperience: union(existing.educationExperience, candidate.educationExperience),
    updatedAt: nowIso(),
  };
  const evidence = Object.fromEntries(Object.entries(candidate).filter(([, value]) => value !== null && (!Array.isArray(value) || value.length)).map(([key]) => [key, evidenceMessageId]));
  if (!Object.keys(evidence).length) return existing;
  await env.RI_db.prepare(
    `INSERT INTO worker_profiles (
       worker_id, role, department, total_experience_years, current_role_experience_years,
       assigned_processes_json, assigned_equipment_json, responsibilities_json,
       qualifications_json, expertise_json, education_experience_json, evidence_json, updated_at
     ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(worker_id) DO UPDATE SET
       role=excluded.role, department=excluded.department,
       total_experience_years=excluded.total_experience_years,
       current_role_experience_years=excluded.current_role_experience_years,
       assigned_processes_json=excluded.assigned_processes_json,
       assigned_equipment_json=excluded.assigned_equipment_json,
       responsibilities_json=excluded.responsibilities_json,
       qualifications_json=excluded.qualifications_json,
       expertise_json=excluded.expertise_json,
       education_experience_json=excluded.education_experience_json,
       evidence_json=json_patch(worker_profiles.evidence_json, excluded.evidence_json),
       updated_at=excluded.updated_at`,
  ).bind(
    workerId, updated.role, updated.department, updated.totalExperienceYears, updated.currentRoleExperienceYears,
    JSON.stringify(updated.assignedProcesses), JSON.stringify(updated.assignedEquipment), JSON.stringify(updated.responsibilities),
    JSON.stringify(updated.qualifications), JSON.stringify(updated.expertise), JSON.stringify(updated.educationExperience),
    JSON.stringify(evidence), updated.updatedAt,
  ).run();
  return updated;
}

export async function nextProfileQuestion(env: RuntimeEnv, profile: WorkerProfile, latestAnswer: string, language: Language) {
  const missingFields = missingRequiredProfileFields(profile);
  try {
    const text = await openaiText(env, `あなたは作業員への初回インタビューを始める自然な聞き手です。
プロフィール質問票のように項目を順番に聞かず、直前の回答に関心を示しながら、まだ分からない背景を一つだけ自然に聞いてください。
初回セッションでは、現在の役割、総経験年数、現在業務の経験年数、担当工程、担当設備、担当業務を最終的に網羅します。
次は未確認項目の中から直前の話に自然につながるものを一つ選んでください。
一度に質問は一つ、短くしてください。${language === 'ja' ? '日本語' : language === 'en' ? '英語' : 'ドイツ語'}で発話だけを返してください。

現在のプロフィール:
${JSON.stringify(profile)}

未確認の必須項目:
${JSON.stringify(missingFields)}

直前の回答:
${latestAnswer}`);
    if (text.trim()) return text.trim();
  } catch (error) {
    console.error('Profile question generation failed', error);
  }
  if (profile.totalExperienceYears === null && profile.currentRoleExperienceYears === null) return language === 'ja' ? '今のお仕事は、どれくらい続けていらっしゃるんですか？' : profileStarters[language];
  if (!profile.assignedProcesses.length) return language === 'ja' ? '最近は、どんな工程や仕事を担当することが多いですか？' : profileStarters[language];
  return language === 'ja' ? '今の仕事の中で、ご自身が特に経験を積んできたと感じるのはどのあたりですか？' : profileStarters[language];
}

function memoryItems(info: ExtractedInfo) {
  const items: Array<{ type: LongTermMemoryType; content: string }> = [];
  for (const value of info.practices) items.push({ type: 'work_knowledge', content: value });
  for (const value of info.reasons) items.push({ type: 'decision_criterion', content: value });
  for (const value of info.values) items.push({ type: 'value', content: value });
  for (const value of info.personal_meanings) items.push({ type: 'work_philosophy', content: value });
  for (const value of info.irregular_situations) items.push({ type: 'trouble_experience', content: value });
  for (const value of info.irregular_responses) items.push({ type: 'tacit_knowledge', content: value });
  return items;
}

export async function persistExtractedMemories(
  env: RuntimeEnv,
  workerId: string,
  sessionId: string,
  evidenceMessageId: string,
  info: ExtractedInfo,
) {
  for (const item of memoryItems(info)) {
    const content = item.content.trim();
    if (!content) continue;
    const existing = await env.RI_db.prepare(
      "SELECT id FROM long_term_memories WHERE worker_id = ? AND type = ? AND content = ? AND status = 'active'",
    ).bind(workerId, item.type, content).first();
    if (existing) continue;
    await env.RI_db.prepare(
      `INSERT INTO long_term_memories (id, worker_id, type, content, source_session_id, evidence_message_id)
       VALUES (?, ?, ?, ?, ?, ?)`,
    ).bind(randomId('mem'), workerId, item.type, content, sessionId, evidenceMessageId).run();
  }
  const resolvedThemes: string[] = [];
  if (info.situations.length && info.practices.length) resolvedThemes.push('対象業務の流れ・状況');
  if (info.reasons.length || info.values.length || info.sources.length || info.personal_meanings.length) resolvedThemes.push('判断理由・経験・価値観');
  if (info.irregular_situations.length && info.irregular_responses.length) resolvedThemes.push('イレギュラー状況と対応');
  for (const theme of resolvedThemes) {
    await env.RI_db.prepare(
      "UPDATE long_term_memories SET status = 'resolved', updated_at = ? WHERE worker_id = ? AND type = 'unexplored_theme' AND content = ? AND status = 'active'",
    ).bind(nowIso(), workerId, theme).run();
  }
}

export async function finalizeSessionMemory(env: RuntimeEnv, workerId: string, sessionId: string, state: InterviewState) {
  const topics = [...new Set([state.target_work, ...state.known_facts].filter((item): item is string => Boolean(item)))].slice(0, 20);
  const unresolved: string[] = [];
  if (state.task_coverage < 0.7) unresolved.push('対象業務の流れ・状況');
  if (state.task_depth < 5) unresolved.push('判断理由・経験・価値観');
  if (state.irregular_coverage < 0.7) unresolved.push('イレギュラー状況と対応');
  const summary = topics.length ? topics.join('。') : 'このセッションでは十分な業務情報を抽出できませんでした。';
  await env.RI_db.prepare(
    `INSERT INTO session_summaries (session_id, worker_id, summary, topics_json, unresolved_topics_json, final_state_json, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(session_id) DO UPDATE SET summary=excluded.summary, topics_json=excluded.topics_json,
       unresolved_topics_json=excluded.unresolved_topics_json, final_state_json=excluded.final_state_json, updated_at=excluded.updated_at`,
  ).bind(sessionId, workerId, summary, JSON.stringify(topics), JSON.stringify(unresolved), JSON.stringify(state), nowIso()).run();
  for (const theme of unresolved) {
    const exists = await env.RI_db.prepare(
      "SELECT id FROM long_term_memories WHERE worker_id = ? AND type = 'unexplored_theme' AND content = ? AND status = 'active'",
    ).bind(workerId, theme).first();
    if (!exists) await env.RI_db.prepare(
      `INSERT INTO long_term_memories (id, worker_id, type, content, source_session_id, confidence)
       VALUES (?, ?, 'unexplored_theme', ?, ?, 1.0)`,
    ).bind(randomId('mem'), workerId, theme, sessionId).run();
  }
}
