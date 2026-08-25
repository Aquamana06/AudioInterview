import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { createInterface } from 'node:readline/promises';
import { stdin as input, stdout as output } from 'node:process';
import { randomUUID } from 'node:crypto';
import { firstUtterance, initialState, runInterviewTurn } from '../worker/agent.js';
import { generateSessionStarter, runContextualInterviewTurn } from '../worker/longitudinal-agent.js';
import { selectRelevantMemory } from '../worker/longitudinal-memory.js';
import { extractSessionMemory } from '../worker/longitudinal-openai.js';
import { emptyProfile } from '../worker/longitudinal-types.js';
import { generateProfileInterviewStarter, runProfileInterviewTurn } from '../worker/profile-interview-agent.js';
import type { ParticipantMemory, SessionMemoryUpdate, StoredMemoryEdge, StoredMemoryNode } from '../worker/longitudinal-types.js';
import type { InterviewState, Language, MessageRow, RuntimeEnv } from '../worker/types.js';

type CliOptions = {
  language: Language;
  showInternals: boolean;
  interviewModel: InterviewModelName;
  llmModel?: string;
  participantId: string;
};

type InterviewModelName = 'original' | 'longitudinal';

const languages = new Set<Language>(['ja', 'en', 'de']);
const interviewModels = new Set<InterviewModelName>(['original', 'longitudinal']);

function parseArgs(argv: string[]): CliOptions {
  const options: CliOptions = { language: 'ja', showInternals: true, interviewModel: 'longitudinal', participantId: 'default' };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--debug') {
      options.showInternals = true;
      continue;
    }
    if (arg === '--no-debug' || arg === '--no-internals') {
      options.showInternals = false;
      continue;
    }
    if (arg === '--lang' || arg === '--language') {
      const value = argv[index + 1] as Language | undefined;
      if (!value || !languages.has(value)) {
        throw new Error('--lang は ja, en, de のいずれかを指定してください。');
      }
      options.language = value;
      index += 1;
      continue;
    }
    if (arg.startsWith('--lang=')) {
      const value = arg.slice('--lang='.length) as Language;
      if (!languages.has(value)) throw new Error('--lang は ja, en, de のいずれかを指定してください。');
      options.language = value;
      continue;
    }
    if (arg === '--model' || arg === '-m') {
      const value = argv[index + 1] as InterviewModelName | undefined;
      if (!value || !interviewModels.has(value)) throw new Error('--model は original または longitudinal を指定してください。');
      options.interviewModel = value;
      index += 1;
      continue;
    }
    if (arg.startsWith('--model=')) {
      const value = arg.slice('--model='.length) as InterviewModelName;
      if (!interviewModels.has(value)) throw new Error('--model は original または longitudinal を指定してください。');
      options.interviewModel = value;
      continue;
    }
    if (arg === '--llm-model') {
      const value = argv[index + 1];
      if (!value) throw new Error('--llm-model にOpenAIモデル名を指定してください。');
      options.llmModel = value;
      index += 1;
      continue;
    }
    if (arg.startsWith('--llm-model=')) {
      options.llmModel = arg.slice('--llm-model='.length);
      continue;
    }
    if (arg === '--participant' || arg === '--user') {
      const value = argv[index + 1];
      if (!value) throw new Error('--participant に参加者IDを指定してください。');
      options.participantId = value;
      index += 1;
      continue;
    }
    if (arg.startsWith('--participant=')) {
      options.participantId = arg.slice('--participant='.length);
      continue;
    }
    if (arg === '--help' || arg === '-h') {
      printHelp();
      process.exit(0);
    }
    throw new Error(`不明なオプションです: ${arg}`);
  }

  return options;
}

function printHelp() {
  console.log(`ターミナル用インタビュー確認

使い方:
  ./terminal-interview.mjs --model longitudinal --participant USER_ID
  ./terminal-interview.mjs --model original
  ./terminal-interview.mjs --model longitudinal --llm-model gpt-5.5
  ./terminal-interview.mjs --no-debug

インタビューモデル:
  original       既存の単発インタビューモデル
  longitudinal   過去記憶を利用する縦断型モデル（既定）

入力中コマンド:
  /state    現在の内部 state を表示
  /history  対話履歴を表示
  /memory   この参加者の長期記憶を表示
  /help     ヘルプを表示
  /quit     終了
`);
}

function loadDevVars(root: string) {
  const path = join(root, '.dev.vars');
  if (!existsSync(path)) return;

  const lines = readFileSync(path, 'utf8').split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;

    const equals = trimmed.indexOf('=');
    if (equals < 1) continue;

    const key = trimmed.slice(0, equals).trim();
    let value = trimmed.slice(equals + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }

    process.env[key] ??= value;
  }
}

function makeMessage(role: 'system' | 'user', content: string, language: Language, sessionId: string, meta?: unknown): MessageRow {
  const now = new Date().toISOString();
  return {
    id: `cli_${Date.now()}_${Math.random().toString(16).slice(2)}`,
    session_id: sessionId,
    role,
    content,
    input_mode: role === 'user' ? 'text' : 'system',
    language,
    meta_json: meta ? JSON.stringify(meta) : null,
    created_at: now,
    updated_at: now,
  };
}

function makeEnv(model?: string): RuntimeEnv {
  return {
    RI_db: undefined as unknown as D1Database,
    OPENAI_API_KEY: process.env.OPENAI_API_KEY,
    OPENAI_TEXT_MODEL: model ?? process.env.OPENAI_TEXT_MODEL,
    OPENAI_TRANSCRIBE_MODEL: process.env.OPENAI_TRANSCRIBE_MODEL,
  };
}

function printState(state: InterviewState) {
  console.log(JSON.stringify(state, null, 2));
}

function formatNumber(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

function printList(label: string, values: string[]) {
  if (!values.length) return;
  console.log(`  ${label}:`);
  for (const value of values) {
    console.log(`    - ${value}`);
  }
}

function printInternals(result: Awaited<ReturnType<typeof runContextualInterviewTurn>>) {
  console.log('\n--- internal ---');
  console.log(`状態: ${result.stateLabel}`);
  console.log(`対象業務: ${result.state.target_work ?? '未特定'}`);
  console.log(
    [
      `turn=${result.state.turn_count}`,
      `網羅性=${formatNumber(result.state.task_coverage)}`,
      `深さ=${formatNumber(result.state.task_depth)}`,
      `イレギュラー網羅=${formatNumber(result.state.irregular_coverage)}`,
      `rapport=${formatNumber(result.state.rapport)}`,
    ].join(' / '),
  );

  console.log('抽出項目:');
  if (result.extracted.target_work) console.log(`  target_work: ${result.extracted.target_work}`);
  printList('situations', result.extracted.situations);
  printList('practices', result.extracted.practices);
  printList('reasons', result.extracted.reasons);
  printList('values', result.extracted.values);
  printList('sources', result.extracted.sources);
  printList('irregular_situations', result.extracted.irregular_situations);
  printList('irregular_responses', result.extracted.irregular_responses);
  printList('persona_notes', result.extracted.persona_notes);
  printList('emotions', result.extracted.emotions);
  printList('user_questions', result.extracted.user_questions);
  printList('signs_of_friction', result.extracted.signs_of_friction);
  printList('signs_of_resistance', result.extracted.signs_of_resistance);
  printList('signs_of_no_information', result.extracted.signs_of_no_information);
  if (result.extracted.wants_to_stop) console.log('  wants_to_stop: true');

  if ('profileExtraction' in result) {
    const profile = result.profileExtraction as Record<string, unknown>;
    console.log('初回プロフィール抽出:');
    for (const [key, value] of Object.entries(profile)) {
      if (Array.isArray(value)) printList(key, value as string[]);
      else if (value === true) console.log(`  ${key}: true`);
    }
  }

  console.log('会話方針:');
  console.log(`  guidance: ${result.guide.guidance}`);
  console.log(`  should_ask_question: ${result.guide.should_ask_question}`);
  console.log(`  should_end: ${result.guide.should_end}`);
  if (result.guide.should_repair) console.log('  should_repair: true');
  if (result.guide.should_answer_user_question) console.log('  should_answer_user_question: true');
  if (result.guide.dice_hint) console.log(`  dice_hint: ${result.guide.dice_hint}`);
  printList('priorities', result.guide.priorities);
  console.log('--- /internal ---\n');
}

function printHistory(messages: MessageRow[]) {
  for (const message of messages) {
    const speaker = message.role === 'system' ? 'interviewer' : 'interviewee';
    console.log(`[${speaker}] ${message.content}`);
  }
}

type LocalParticipant = ParticipantMemory & { recent_starters: string[] };
type LocalMemoryFile = { participants: Record<string, LocalParticipant> };

function emptyParticipant(accountId: string): LocalParticipant {
  return { account_id: accountId, session_count: 0, profile: emptyProfile(), recent_summaries: [], nodes: [], edges: [], recent_starters: [] };
}

function readLocalMemory(path: string): LocalMemoryFile {
  if (!existsSync(path)) return { participants: {} };
  try {
    return JSON.parse(readFileSync(path, 'utf8')) as LocalMemoryFile;
  } catch {
    console.warn(`長期記憶ファイルを読めなかったため、新規に開始します: ${path}`);
    return { participants: {} };
  }
}

function unique(current: string[], incoming: string[]) {
  return [...new Set([...current, ...incoming].filter(Boolean))];
}

function applyLocalUpdate(memory: LocalParticipant, sessionId: string, update: SessionMemoryUpdate): LocalParticipant {
  const nodes = [...memory.nodes];
  const edges = [...memory.edges];
  const localKeys = new Map<string, string>();
  for (const node of update.nodes) {
    const canonical = `${node.kind}:${node.text}`;
    const existing = nodes.find((item) => `${item.kind}:${item.text}` === canonical);
    const id = existing?.id ?? `mem_${randomUUID()}`;
    localKeys.set(node.key, id);
    if (existing) {
      existing.last_session_id = sessionId;
      existing.confidence = Math.max(existing.confidence, node.confidence);
      existing.status = node.status;
      existing.evidence_message_ids = unique(existing.evidence_message_ids, node.evidence_message_ids);
    } else {
      nodes.push({ ...node, id, first_session_id: sessionId, last_session_id: sessionId });
    }
  }
  for (const edge of update.edges) {
    const fromId = localKeys.get(edge.from_key);
    const toId = localKeys.get(edge.to_key);
    if (!fromId || !toId) continue;
    const existing = edges.find((item) => item.from_node_id === fromId && item.to_node_id === toId && item.relation === edge.relation);
    if (existing) {
      existing.last_session_id = sessionId;
      existing.confidence = Math.max(existing.confidence, edge.confidence);
      existing.explicitness = existing.explicitness === 'explicit' || edge.explicitness === 'explicit' ? 'explicit' : 'inferred';
      existing.evidence_message_ids = unique(existing.evidence_message_ids, edge.evidence_message_ids);
    } else {
      edges.push({ ...edge, id: `edge_${randomUUID()}`, from_node_id: fromId, to_node_id: toId, first_session_id: sessionId, last_session_id: sessionId } as StoredMemoryEdge);
    }
  }
  const patch = update.profile_patch;
  return {
    ...memory,
    session_count: memory.session_count + 1,
    profile: {
      role: patch.role ?? memory.profile.role,
      years_of_experience: patch.years_of_experience ?? memory.profile.years_of_experience,
      typical_day: unique(memory.profile.typical_day, patch.typical_day),
      responsibilities: unique(memory.profile.responsibilities, patch.responsibilities),
      collaborators: unique(memory.profile.collaborators, patch.collaborators),
    },
    recent_summaries: update.summary
      ? [{ session_id: sessionId, summary: update.summary, ended_at: new Date().toISOString() }, ...memory.recent_summaries]
      : memory.recent_summaries,
    nodes: nodes as StoredMemoryNode[],
    edges,
  };
}

async function main() {
  const root = process.env.AUDIOINTERVIEW_ROOT ?? process.cwd();
  loadDevVars(root);

  const options = parseArgs(process.argv.slice(2));
  const env = makeEnv(options.llmModel);
  const memoryPath = join(root, '.terminal-interview-memory.local');
  const memoryFile = readLocalMemory(memoryPath);
  let participantMemory = memoryFile.participants[options.participantId] ?? emptyParticipant(options.participantId);
  const sessionId = `cli_${randomUUID()}`;
  const isFirstLongitudinalSession = options.interviewModel === 'longitudinal' && participantMemory.session_count === 0;
  let state = initialState();
  let longitudinalDepthStagnationCount = 0;
  const messages: MessageRow[] = [];

  if (!env.OPENAI_API_KEY) {
    console.warn('OPENAI_API_KEY が見つかりません。.dev.vars または環境変数に設定すると実際の生成で確認できます。');
  }

  console.log(`ターミナル用インタビュー確認を開始します。interview-model=${options.interviewModel} / llm=${env.OPENAI_TEXT_MODEL ?? 'gpt-5.5'} / participant=${options.participantId} / 過去${participantMemory.session_count}セッション`);
  const opening = isFirstLongitudinalSession
    ? await generateProfileInterviewStarter(env, options.language)
    : options.interviewModel === 'longitudinal'
      ? await generateSessionStarter(env, {
        accountId: options.participantId,
        language: options.language,
        sessionCount: participantMemory.session_count,
        recentStarters: participantMemory.recent_starters,
        profile: participantMemory.profile,
        })
      : firstUtterance(options.language);
  if (options.interviewModel === 'longitudinal') {
    participantMemory.recent_starters = [opening, ...participantMemory.recent_starters].slice(0, 5);
  }
  messages.push(makeMessage('system', opening, options.language, sessionId, { stateSnapshot: state }));
  console.log(`\ninterviewer: ${opening}`);

  const rl = createInterface({ input, output });
  rl.on('SIGINT', () => {
    console.log('\nCtrl+Cを受け取りました。このセッションを保存して終了します。');
    rl.write('/quit\n');
  });
  try {
    while (true) {
      const answer = (await rl.question('\ninterviewee> ')).trim();
      if (!answer) {
        console.log('（入力が空です。回答を入力するか、終了する場合は /quit と入力してください）');
        continue;
      }

      if (answer === '/quit' || answer === '/exit') break;
      if (answer === '/help') {
        printHelp();
        continue;
      }
      if (answer === '/state') {
        printState(state);
        continue;
      }
      if (answer === '/history') {
        printHistory(messages);
        continue;
      }
      if (answer === '/memory') {
        console.log(JSON.stringify(participantMemory, null, 2));
        continue;
      }

      messages.push(makeMessage('user', answer, options.language, sessionId));
      process.stdout.write('interviewer is thinking...\r');
      const depthBeforeTurn = state.task_depth;

      const result = isFirstLongitudinalSession
        ? await runProfileInterviewTurn(env, state, answer, messages, options.language, participantMemory.profile)
        : options.interviewModel === 'longitudinal'
          ? await runContextualInterviewTurn(
            env,
            state,
            answer,
            messages,
            options.language,
            selectRelevantMemory(participantMemory, answer),
            longitudinalDepthStagnationCount,
            )
          : await runInterviewTurn(env, state, answer, messages, options.language);
      state = result.state;
      if (!isFirstLongitudinalSession && options.interviewModel === 'longitudinal') {
        longitudinalDepthStagnationCount = state.task_depth === depthBeforeTurn ? longitudinalDepthStagnationCount + 1 : 0;
      }
      messages.push(
        makeMessage('system', result.text, options.language, sessionId, {
          extracted: result.extracted,
          guide: result.guide,
          stateSnapshot: result.state,
        }),
      );

      process.stdout.write(' '.repeat(28) + '\r');
      if (options.showInternals) printInternals(result);
      console.log(`interviewer: ${result.text}`);
      if (result.stateLabel === 'end') break;
    }
  } finally {
    rl.close();
  }

  if (options.interviewModel === 'longitudinal' && messages.some((message) => message.role === 'user')) {
    console.log('\nセッションの長期記憶を整理しています...');
    const update = await extractSessionMemory(env, {
      accountId: options.participantId,
      sessionId,
      language: options.language,
      messages,
      previousMemory: participantMemory,
    });
    participantMemory = applyLocalUpdate(participantMemory, sessionId, update);
    if (update.summary) console.log(`session summary: ${update.summary}`);
  }
  if (options.interviewModel === 'longitudinal') {
    memoryFile.participants[options.participantId] = participantMemory;
    writeFileSync(memoryPath, `${JSON.stringify(memoryFile, null, 2)}\n`, 'utf8');
    console.log(`長期記憶を保存しました: ${memoryPath}`);
  }
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
