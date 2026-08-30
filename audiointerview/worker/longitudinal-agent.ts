import { runInterviewTurn } from './agent.js';
import { openaiText } from './openai.js';
import type { AgentResult, InterviewState, Language, MessageRow, RuntimeEnv } from './types.js';
import type { ContextualMemory, StarterInput } from './longitudinal-types.js';

const fallbackStarters: Record<Language, string[]> = {
  ja: [
    '先ほどはどんな業務をしていましたか？',
    '今日は直前まで、どんなお仕事をされていたんですか？',
    'さっき取り組んでいた業務について教えてもらえますか？',
    '先ほどのお仕事では、どんなことをされていましたか？',
    '今日ここへ来る前は、どんな業務をしていたのでしょうか？',
  ],
  en: [
    'What kind of work were you doing earlier?',
    'What were you working on just before this interview?',
    'Could you tell me about the work you were doing earlier today?',
  ],
  de: [
    'Welche Arbeit haben Sie vorhin gemacht?',
    'Woran haben Sie unmittelbar vor diesem Gespräch gearbeitet?',
    'Können Sie mir von Ihrer Arbeit vorhin erzählen?',
  ],
};

function selectFallback(input: StarterInput) {
  const candidates = fallbackStarters[input.language];
  const unused = candidates.filter((candidate) => !input.recentStarters.includes(candidate));
  const pool = unused.length ? unused : candidates;
  return pool[input.sessionCount % pool.length];
}

export async function generateSessionStarter(env: RuntimeEnv, input: StarterInput) {
  const fallback = selectFallback(input);
  if (!env.OPENAI_API_KEY) return fallback;

  const language = input.language === 'ja' ? '日本語' : input.language === 'en' ? '英語' : 'ドイツ語';
  const prompt = `反復型インタビューの開始発話を${language}で1文だけ生成してください。

目的は毎回共通で、参加者が「先ほどしていた具体的な業務」を話し始められるようにすることです。
- 質問の目的や深さを変えない。
- 過去の価値観や過去の業務を開始時点で持ち出さない。今日のリアルタイムな経験を起点にする。
- 自然で短く、答えやすい一つの質問にする。
- 「工夫」「価値観」「調整行動」という分析用語は使わない。
- 最近使った表現と同じ言い回しを避ける。
- 挨拶や解説を付けず、質問文だけを返す。

最近の開始発話: ${JSON.stringify(input.recentStarters)}`;

  try {
    const text = (await openaiText(env, prompt)).trim().replace(/^['“”「]|['“”」]$/g, '');
    if (!text || input.recentStarters.includes(text) || text.length > 140) return fallback;
    return text;
  } catch (error) {
    console.error('Failed to generate session starter', error);
    return fallback;
  }
}

function memoryMessage(memory: ContextualMemory, language: Language): MessageRow | null {
  if (!memory.nodes.length && !memory.summaries.length && !memory.profile.role) return null;
  const context = {
    profile: memory.profile,
    relevant_session_summaries: memory.summaries,
    relevant_known_information: memory.nodes.slice(0, 12).map(({ id, kind, text, status, confidence, first_session_id, last_session_id }) => ({
      id,
      kind,
      text,
      status,
      confidence,
      first_session_id,
      last_session_id,
    })),
    relevant_connections: memory.edges.slice(0, 12).map(({ relation, explicitness, confidence, from_node_id, to_node_id }) => ({ relation, explicitness, confidence, from_node_id, to_node_id })),
  };
  return {
    id: 'longitudinal_memory_context',
    session_id: 'memory',
    role: 'system',
    content: `【過去セッションから得た参照情報】\n${JSON.stringify(context)}\nこの情報は今回の回答ではない。今回の具体的な業務と調整行動を起点にすること。関連する場合だけ、既知の事実として自然に接続する。過去の理由や価値観を今回にも当てはまると決めつけず、本人が語れる余地を残す。`,
    input_mode: 'system',
    language,
    meta_json: JSON.stringify({ kind: 'longitudinal_memory_context' }),
    created_at: new Date(0).toISOString(),
    updated_at: new Date(0).toISOString(),
  };
}

export async function runContextualInterviewTurn(
  env: RuntimeEnv,
  state: InterviewState,
  userInput: string,
  currentSessionHistory: MessageRow[],
  language: Language,
  relevantMemory: ContextualMemory,
  depthStagnationCount = 0,
): Promise<AgentResult> {
  const context = memoryMessage(relevantMemory, language);
  const pivotInstruction = depthStagnationCount >= 3 ? depthPivotMessage(language, Boolean(context)) : null;
  const history = [context, pivotInstruction, ...currentSessionHistory].filter((message): message is MessageRow => Boolean(message));
  const result = await runInterviewTurn(env, state, userInput, history, language);
  result.state.task_depth = Math.max(result.state.task_depth, calculateFlexibleDepth(result.state));
  return result;
}

function calculateFlexibleDepth(state: InterviewState) {
  if (!state.target_work) return 0;

  const has = (prefix: string) => state.known_facts.some((fact) => fact.startsWith(prefix));
  if (has('個人的意味・価値観の形成背景・真髄:')) return 6;
  if (has('価値観:')) return 5;
  if (has('源泉:')) return 4;
  if (has('理由:')) return 3;
  if (has('業務上の実践:')) return 2;
  return 1;
}

function depthPivotMessage(language: Language, hasMemory: boolean): MessageRow {
  const content = hasMemory
    ? `【このターンだけの質問方針】depthが3回答ターン以上変化していない。これまでと同じ聞き方をやめ、質問の方向を大きく変えること。【過去セッションから得た参照情報】に含まれる過去セッションの具体情報、または初回プロフィールの仕事情報を一つ必ず発話に反映し、今回の対象業務とのつながり・違い・変化のいずれかを一問だけ尋ねること。過去情報が今回も当てはまるとは決めつけず、本人が訂正できる聞き方にすること。`
    : `【このターンだけの質問方針】depthが3回答ターン以上変化していない。これまでと同じ聞き方をやめ、現在の会話で既知の具体的な業務場面・実践・経験を一つ必ず使い、比較・変化・葛藤・きっかけのいずれかへ質問の方向を大きく変えること。理由を同じ表現で聞き直さないこと。`;
  return {
    id: 'terminal_depth_pivot',
    session_id: 'terminal',
    role: 'system',
    content,
    input_mode: 'system',
    language,
    meta_json: JSON.stringify({ kind: 'terminal_depth_pivot' }),
    created_at: new Date(0).toISOString(),
    updated_at: new Date(0).toISOString(),
  };
}
