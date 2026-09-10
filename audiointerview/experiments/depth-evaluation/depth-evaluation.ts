import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { basename, join, resolve } from 'node:path';
import { createInterface } from 'node:readline/promises';
import { stdin as input, stdout as output } from 'node:process';
import { randomUUID } from 'node:crypto';
import { firstUtterance, initialState } from '../../worker/agent.js';
import { runDepthEvaluationTurn } from './depth-evaluation-agent.js';
import type { AgentResult, InterviewState, Language, MessageRow, RuntimeEnv } from '../../worker/types.js';

type Model = 'original' | 'longitudinal';
type Options = { language: Language; model: Model; llmModel?: string; outputDir: string };

type TurnRecord = {
  turn: number;
  user: { text: string; created_at: string };
  agent: {
    text: string;
    depth: number;
    depth_before: number;
    depth_delta: number;
    extracted: AgentResult['extracted'];
    guide: AgentResult['guide'];
    state: InterviewState;
  };
  human_annotation: {
    depth: number | null;
    note: string | null;
    annotated_at: string | null;
  };
};

type EvaluationFile = {
  schema_version: 1;
  session_id: string;
  started_at: string;
  ended_at: string | null;
  model: Model;
  language: Language;
  llm_model: string | null;
  turns: TurnRecord[];
};

const languages = new Set<Language>(['ja', 'en', 'de']);
const models = new Set<Model>(['original', 'longitudinal']);

function parseArgs(argv: string[]): Options {
  const options: Options = { language: 'ja', model: 'original', outputDir: join(process.cwd(), 'sample_data', 'depth-evaluations') };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = () => {
      const value = argv[++i];
      if (!value) throw new Error(`${arg} の値を指定してください。`);
      return value;
    };
    if (arg === '--lang' || arg === '--language') options.language = requireChoice(next(), languages, '--lang は ja, en, de のいずれかです。');
    else if (arg.startsWith('--lang=')) options.language = requireChoice(arg.slice(7), languages, '--lang は ja, en, de のいずれかです。');
    else if (arg === '--model' || arg === '-m') options.model = requireChoice(next(), models, '--model は original または longitudinal です。');
    else if (arg.startsWith('--model=')) options.model = requireChoice(arg.slice(8), models, '--model は original または longitudinal です。');
    else if (arg === '--llm-model') options.llmModel = next();
    else if (arg.startsWith('--llm-model=')) options.llmModel = arg.slice(12);
    else if (arg === '--output-dir') options.outputDir = resolve(next());
    else if (arg.startsWith('--output-dir=')) options.outputDir = resolve(arg.slice(13));
    else if (arg === '--help' || arg === '-h') { printHelp(); process.exit(0); }
    else throw new Error(`不明なオプションです: ${arg}`);
  }
  return options;
}

function requireChoice<T extends string>(value: string, choices: Set<T>, message: string): T {
  if (!choices.has(value as T)) throw new Error(message);
  return value as T;
}

function printHelp() {
  console.log(`depth判定評価用ターミナルインタビュー

使い方:
  npm run depth-evaluation
  npm run depth-evaluation -- --model longitudinal --llm-model gpt-5.5
  npm run depth-evaluation -- --output-dir ./sample_data/my-run

各回答の後に、あなたが感じた depth (0〜6) と任意のメモを入力します。
  0: 対象業務も不明 / 1: 対象業務のみ / 2: 実践
  3: 理由 / 4: 源泉 / 5: 価値観 / 6: 個人的意味・仕事の真髄

--model は過去の実験記録との互換用です。質問生成は実験用エージェントで共通です。

入力中コマンド:
  /history  対話履歴と評価を表示
  /state    現在のagent stateを表示
  /save     現在までの内容を保存
  /skip     今回の人間評価を未評価のまま保存
  /quit     保存して終了
`);
}

function loadDevVars(root: string) {
  const path = join(root, '.dev.vars');
  if (!existsSync(path)) return;
  for (const line of readFileSync(path, 'utf8').split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const equals = trimmed.indexOf('=');
    if (equals < 1) continue;
    const key = trimmed.slice(0, equals).trim();
    let value = trimmed.slice(equals + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
    process.env[key] ??= value;
  }
}

function makeEnv(model?: string): RuntimeEnv {
  return { RI_db: undefined as unknown as D1Database, OPENAI_API_KEY: process.env.OPENAI_API_KEY, OPENAI_TEXT_MODEL: model ?? process.env.OPENAI_TEXT_MODEL };
}

function message(role: 'system' | 'user', content: string, language: Language, sessionId: string): MessageRow {
  const now = new Date().toISOString();
  return { id: `eval_${randomUUID()}`, session_id: sessionId, role, content, input_mode: role === 'user' ? 'text' : 'system', language, meta_json: null, created_at: now, updated_at: now };
}

function save(filePath: string, evaluation: EvaluationFile, ended = false) {
  if (ended) evaluation.ended_at = new Date().toISOString();
  writeFileSync(filePath, `${JSON.stringify(evaluation, null, 2)}\n`, 'utf8');
}

function printHistory(evaluation: EvaluationFile) {
  for (const turn of evaluation.turns) {
    const annotation = turn.human_annotation.depth === null ? '未評価' : `${turn.human_annotation.depth}${turn.human_annotation.note ? ` (${turn.human_annotation.note})` : ''}`;
    console.log(`\n#${turn.turn} human=${annotation} / agent=${turn.agent.depth}`);
    console.log(`interviewee: ${turn.user.text}`);
    console.log(`interviewer: ${turn.agent.text}`);
  }
}

async function annotate(rl: ReturnType<typeof createInterface>, turn: TurnRecord): Promise<'continue' | 'quit'> {
  while (true) {
    const raw = (await rl.question('human depth (0-6, /skip, /quit): ')).trim();
    if (raw === '/skip' || raw === '') return 'continue';
    if (raw === '/quit') return 'quit';
    const match = raw.match(/^([0-6])(?:\s+(.+))?$/);
    if (!match) { console.log('0〜6、または /skip を入力してください。例: 4 理由は具体的だが価値観までは不明'); continue; }
    turn.human_annotation = { depth: Number(match[1]), note: match[2]?.trim() || null, annotated_at: new Date().toISOString() };
    return 'continue';
  }
}

async function main() {
  const root = process.env.AUDIOINTERVIEW_ROOT ?? process.cwd();
  loadDevVars(root);
  const options = parseArgs(process.argv.slice(2));
  mkdirSync(options.outputDir, { recursive: true });
  const sessionId = `depth_${new Date().toISOString().replace(/[:.]/g, '-')}_${randomUUID().slice(0, 8)}`;
  const filePath = join(options.outputDir, `${sessionId}.json`);
  const evaluation: EvaluationFile = { schema_version: 1, session_id: sessionId, started_at: new Date().toISOString(), ended_at: null, model: options.model, language: options.language, llm_model: options.llmModel ?? process.env.OPENAI_TEXT_MODEL ?? null, turns: [] };
  const env = makeEnv(options.llmModel);
  let state = initialState();
  let highDepthCount = 0;
  const messages: MessageRow[] = [];
  const opening = firstUtterance(options.language);
  messages.push(message('system', opening, options.language, sessionId));
  console.log(`depth評価セッションを開始しました。model=${options.model} / file=${filePath}`);
  if (!env.OPENAI_API_KEY) console.warn('OPENAI_API_KEY がありません。フォールバック動作で実行します。');
  console.log(`\ninterviewer: ${opening}`);

  const rl = createInterface({ input, output });
  let shouldQuit = false;
  let interrupted = false;
  rl.on('SIGINT', () => {
    interrupted = true;
    console.log('\nCtrl+Cを受け取りました。ここまでの履歴を保存して終了します。');
    save(filePath, evaluation, true);
    rl.close();
  });
  try {
    while (!shouldQuit && !interrupted) {
      let answer = '';
      try { answer = (await rl.question('\ninterviewee> ')).trim(); } catch { break; }
      if (!answer) continue;
      if (answer === '/quit' || answer === '/exit') break;
      if (answer === '/help') { printHelp(); continue; }
      if (answer === '/history') { printHistory(evaluation); continue; }
      if (answer === '/state') { console.log(JSON.stringify(state, null, 2)); continue; }
      if (answer === '/save') { save(filePath, evaluation); console.log(`保存しました: ${filePath}`); continue; }

      const userMessage = message('user', answer, options.language, sessionId);
      messages.push(userMessage);
      const before = state.task_depth;
      process.stdout.write('interviewer is thinking...\r');
      const result = await runDepthEvaluationTurn(env, state, answer, messages, options.language, highDepthCount);
      process.stdout.write(' '.repeat(30) + '\r');
      state = result.state;
      highDepthCount = result.highDepthCount;
      const turn: TurnRecord = {
        turn: evaluation.turns.length + 1,
        user: { text: answer, created_at: userMessage.created_at },
        agent: { text: result.text, depth: state.task_depth, depth_before: before, depth_delta: state.task_depth - before, extracted: result.extracted, guide: result.guide, state: structuredClone(state) },
        human_annotation: { depth: null, note: null, annotated_at: null },
      };
      evaluation.turns.push(turn);
      messages.push(message('system', result.text, options.language, sessionId));
      console.log(`agent depth: ${state.task_depth} (before=${before}, delta=${state.task_depth - before})`);
      console.log(`interviewer: ${result.text}`);
      if (await annotate(rl, turn) === 'quit') shouldQuit = true;
      save(filePath, evaluation);
      console.log(`記録を保存しました: ${basename(filePath)}`);
      if (result.stateLabel === 'end') break;
    }
  } finally {
    rl.close();
    save(filePath, evaluation, true);
  }
  console.log(`\n評価セッションを保存しました: ${filePath}`);
}

main().catch((error: unknown) => { console.error(error instanceof Error ? error.message : error); process.exit(1); });
