import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { createInterface } from 'node:readline/promises';
import { stdin as input, stdout as output } from 'node:process';
import { firstUtterance, initialState, runInterviewTurn } from '../worker/agent.js';
import type { InterviewState, Language, MessageRow, RuntimeEnv } from '../worker/types.js';

type CliOptions = {
  language: Language;
  showInternals: boolean;
};

const languages = new Set<Language>(['ja', 'en', 'de']);

function parseArgs(argv: string[]): CliOptions {
  const options: CliOptions = { language: 'ja', showInternals: true };

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
  ./terminal-interview.mjs [--lang ja|en|de] [--debug]
  ./terminal-interview.mjs --no-debug

入力中コマンド:
  /state    現在の内部 state を表示
  /history  対話履歴を表示
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

function makeMessage(role: 'system' | 'user', content: string, language: Language, meta?: unknown): MessageRow {
  const now = new Date().toISOString();
  return {
    id: `cli_${Date.now()}_${Math.random().toString(16).slice(2)}`,
    session_id: 'cli',
    role,
    content,
    input_mode: role === 'user' ? 'text' : 'system',
    language,
    meta_json: meta ? JSON.stringify(meta) : null,
    created_at: now,
    updated_at: now,
  };
}

function makeEnv(): RuntimeEnv {
  return {
    RI_db: undefined as unknown as D1Database,
    OPENAI_API_KEY: process.env.OPENAI_API_KEY,
    OPENAI_TEXT_MODEL: process.env.OPENAI_TEXT_MODEL,
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

function printInternals(result: Awaited<ReturnType<typeof runInterviewTurn>>) {
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

async function main() {
  const root = process.env.AUDIOINTERVIEW_ROOT ?? process.cwd();
  loadDevVars(root);

  const options = parseArgs(process.argv.slice(2));
  const env = makeEnv();
  let state = initialState();
  const messages: MessageRow[] = [];

  if (!env.OPENAI_API_KEY) {
    console.warn('OPENAI_API_KEY が見つかりません。.dev.vars または環境変数に設定すると実際の生成で確認できます。');
  }

  console.log('ターミナル用インタビュー確認を開始します。終了は /quit です。');
  const opening = firstUtterance(options.language);
  messages.push(makeMessage('system', opening, options.language, { stateSnapshot: state }));
  console.log(`\ninterviewer: ${opening}`);

  const rl = createInterface({ input, output });
  try {
    while (true) {
      const answer = (await rl.question('\ninterviewee> ')).trim();
      if (!answer) continue;

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

      messages.push(makeMessage('user', answer, options.language));
      process.stdout.write('interviewer is thinking...\r');

      const result = await runInterviewTurn(env, state, answer, messages, options.language);
      state = result.state;
      messages.push(
        makeMessage('system', result.text, options.language, {
          extracted: result.extracted,
          guide: result.guide,
          stateSnapshot: result.state,
        }),
      );

      process.stdout.write(' '.repeat(28) + '\r');
      console.log(`interviewer: ${result.text}`);
      if (options.showInternals) printInternals(result);
      if (result.stateLabel === 'end') break;
    }
  } finally {
    rl.close();
  }
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
