import { emptyExtraction, openaiText } from './openai.js';
import {
  assistantPlaceholderInstruction,
  placeholderCorrectionInstruction,
  sanitizeAssistantText,
} from './privacy/outputFilter.js';
import type { AgentResult, ConversationGuide, ExtractedInfo, InterviewState, Language, MessageRow, RuntimeEnv, WorkerContext } from './types.js';

export const endings: Record<Language, string> = {
  ja: 'ありがとうございました。これでインタビューを終了します。',
  en: 'Thank you very much. This concludes the interview.',
  de: 'Vielen Dank. Damit beenden wir das Interview.',
};

const starters: Record<Language, string> = {
  ja: '先ほどはどんな業務をしていましたか？',
  en: 'What kind of work were you doing earlier? Please briefly include the situation at that time.',
  de: 'Welche Arbeit haben Sie vorhin gemacht? Bitte beschreiben Sie kurz auch die damalige Situation.',
};

const languageNames: Record<Language, string> = {
  ja: 'Japanese',
  en: 'English',
  de: 'German',
};

export function firstUtterance(language: Language) {
  return starters[language];
}

export function initialState(): InterviewState {
  return {
    target_work: null,
    task_coverage: 0,
    task_depth: 0,
    irregular_coverage: 0,
    rapport: 0,
    known_facts: [],
    asked_points: [],
    persona_notes: [],
    consecutive_questions: 0,
    turns_since_reflection: 0,
    friction_count: 0,
    resistance_count: 0,
    turn_count: 0,
  };
}

export async function runInterviewTurn(
  env: RuntimeEnv,
  state: InterviewState,
  userInput: string,
  chatHistory: MessageRow[],
  language: Language,
  workerContext?: WorkerContext,
): Promise<AgentResult> {
  const correctedMaskedText = await correctMaskedTranscript(env, userInput);
  const gptUserInput = correctedMaskedText || userInput;
  const extracted = await extractInfo(env, gptUserInput, state, chatHistory, workerContext);
  const nextState = updateStateFromExtraction(structuredClone(state), extracted);
  const guide = buildConversationGuide(nextState, extracted);

  if (extracted.wants_to_stop || guide.should_end) {
    const text = sanitizeAssistantText(endings[language]);
    return {
      text,
      state: nextState,
      stateLabel: 'end',
      extracted,
      guide,
      correctedMaskedText: gptUserInput,
    };
  }

  const generated = await generateUtterance(env, guide, nextState, gptUserInput, chatHistory, workerContext);
  const localized = sanitizeAssistantText(await localizeUtterance(env, generated, language));
  updateAfterUtterance(nextState, localized);

  return {
    text: localized,
    state: nextState,
    stateLabel: 'running',
    extracted,
    guide,
    correctedMaskedText: gptUserInput,
  };
}

export async function correctMaskedTranscript(env: RuntimeEnv, maskedText: string) {
  const prompt = `あなたは音声認識テキストの校正器です。
入力はSemantic Masking済みのテキストだけです。
化学プラントの一般的な文脈を参考に、助詞、文法、一般語の明らかなASR誤認識だけを最小限修正してください。
意味を追加しないでください。
出力は修正後テキストのみです。${placeholderCorrectionInstruction()}

【入力】
${maskedText}`;

  const corrected = (await safeOpenaiText(env, prompt)).trim();
  if (!corrected) return maskedText;
  return corrected;
}

async function extractInfo(env: RuntimeEnv, userInput: string, state: InterviewState, chatHistory: MessageRow[], workerContext?: WorkerContext) {
  const prompt = `あなたは半構造化インタビューの情報抽出器です。
直前のインタビュイ発話から、対象業務に関する情報を構造化してください。

重要:
- キーワード一致ではなく、対話の流れで判断する。
- 想像で補わない。
- 既に分かっていることは、必要に応じて維持してよいが、最新回答にないことを無理に追加しない。
- reason/source は独立した質問項目ではなく、対象業務の深さを高める材料。
- friction は、相手が「さっき言った」「同じこと聞かないで」「今はその話」など、重複・脱線・誤解を指摘している場合。
- user_questions は、相手が質問の意味や範囲を確認している場合。

抽出項目:
- target_work:
  一番最初に話していた主題業務。

- situations:
  混雑、休憩直後、忙しい時間帯、特定の客対応などの状況。

- practices:
  業務中にしていること、仕事の進め方、確認、対応。

- reasons:
  その実践や構えの理由。

- values:
  価値観、本音、仕事観、責任感。

- sources:
  経験、教育、教え、源泉。

- personal_meanings:
  個人的経験・価値観の形成背景・仕事の真髄。

- irregular_situations:
  想定外、例外、イレギュラーな状況。

- irregular_responses:
  一番最初の主題業務に関する，イレギュラー時の対応・構え。

- persona_notes:
  その人の役割、仕事観、人柄、立場に関するメモ。

- emotions:
  疲れ、困惑、葛藤、嫌さ、嬉しさなど。

- user_questions:
  相手からの逆質問や確認。

- signs_of_friction:
  重複、脱線、誤解への不満。

- signs_of_resistance:
  答えづらさ、拒否感、面倒さ

- signs_of_no_information:
  特になし、分からない、覚えていないなど。

- wants_to_stop:
  明確に終了したい場合のみ true。

- profile_update:
  本人の直前発話に明示されたプロフィール情報だけを抽出する。
  role, department, totalExperienceYears, currentRoleExperienceYears, assignedProcesses,
  assignedEquipment, responsibilities, qualifications, expertise, educationExperience を含める。
  過去文脈から再抽出・推測せず、直前発話にないスカラーはnull、配列は[]にする。

【現在の state】
${JSON.stringify(state)}

【作業員プロフィール・過去セッションの記憶（参考文脈。今回の発話として抽出し直さない）】
${JSON.stringify(workerContext ?? null)}

【対話履歴】
${dumpMessages(chatHistory)}

【直前のインタビュイ発話】
${userInput}`;

  const result = await safeOpenaiText(env, prompt, { json: true, schemaName: 'ExtractedInfo' });
  if (!result) return fallbackExtract(userInput);

  try {
    return { ...emptyExtraction, ...JSON.parse(result) } as ExtractedInfo;
  } catch {
    return fallbackExtract(userInput);
  }
}

function updateStateFromExtraction(state: InterviewState, info: ExtractedInfo) {
  state.turn_count += 1;

  if (info.target_work) {
    state.target_work = info.target_work;
    state.task_coverage = Math.max(state.task_coverage, 0.2);
    state.known_facts.push(`対象業務: ${info.target_work}`);
  }

  for (const item of info.situations) state.known_facts.push(`状況: ${item}`);
  if (info.situations.length) state.task_coverage = Math.min(1, state.task_coverage + 0.05);

  for (const item of info.practices) state.known_facts.push(`業務上の実践: ${item}`);
  if (info.practices.length) {
    state.task_coverage = Math.min(1, state.task_coverage + 0.1);
    state.task_depth = Math.max(state.task_depth, 2);
  }

  for (const item of info.reasons) state.known_facts.push(`理由: ${item}`);
  if (info.reasons.length) state.task_depth = Math.max(state.task_depth, 3);

  for (const item of info.sources) state.known_facts.push(`源泉: ${item}`);
  if (info.sources.length) state.task_depth = Math.max(state.task_depth, 4);

  for (const item of info.values) state.known_facts.push(`価値観: ${item}`);
  if (info.values.length) state.task_depth = Math.max(state.task_depth, 5);

  for (const item of info.personal_meanings) state.known_facts.push(`個人的意味・価値観の形成背景・真髄: ${item}`);
  if (info.personal_meanings.length) state.task_depth = Math.max(state.task_depth, 6);

  for (const item of info.irregular_situations) state.known_facts.push(`イレギュラー状況: ${item}`);
  if (info.irregular_situations.length) state.irregular_coverage = Math.min(1, state.irregular_coverage + 0.25);

  for (const item of info.irregular_responses) state.known_facts.push(`イレギュラー時の対応: ${item}`);
  if (info.irregular_responses.length) state.irregular_coverage = Math.min(1, state.irregular_coverage + 0.35);

  for (const item of info.persona_notes) state.persona_notes.push(item);
  if (info.persona_notes.length) state.rapport = Math.min(1, state.rapport + 0.08);

  for (const item of info.emotions) state.known_facts.push(`感情・状態: ${item}`);
  if (info.emotions.length) state.rapport = Math.min(1, state.rapport + 0.05);

  for (const item of info.user_questions) state.known_facts.push(`相手からの確認: ${item}`);

  for (const item of info.signs_of_friction) state.asked_points.push(item);
  if (info.signs_of_friction.length) {
    state.friction_count += 1;
    state.rapport = Math.max(0, state.rapport - 0.12);
  }

  for (const item of info.signs_of_resistance) state.asked_points.push(item);
  if (info.signs_of_resistance.length) {
    state.resistance_count += 1;
    state.rapport = Math.max(0, state.rapport - 0.05);
  }

  for (const item of info.signs_of_no_information) state.asked_points.push(item);

  if (hasInformativeContent(info)) state.rapport = Math.min(1, state.rapport + 0.03);
  trimState(state);
  return state;
}

function buildConversationGuide(state: InterviewState, info: ExtractedInfo): ConversationGuide {
  const base = (guide: Omit<ConversationGuide, 'avoid_reasking' | 'use_as_known'>): ConversationGuide => ({
    ...guide,
    avoid_reasking: buildAvoidReasking(state),
    use_as_known: buildUseAsKnown(state),
  });

  if (shouldEndInterview(state)) {
    return base({
      should_ask_question: false,
      should_end: true,
      guidance: '必要な情報は概ね得られたため、自然に終了する。',
      priorities: ['感謝して終了する'],
    });
  }

  if (info.signs_of_friction.length) {
    return base({
      should_ask_question: false,
      should_end: false,
      should_repair: true,
      guidance:
        '相手が重複・脱線・誤解を指摘している。まず謝る。次に、既に分かっていることを短く正しく言い直す。このターンでは新しい質問をしない。',
      priorities: ['謝る', '既に分かっている内容を正しく言い直す', '質問しない'],
    });
  }

  if (info.user_questions.length) {
    return base({
      should_ask_question: true,
      should_end: false,
      should_answer_user_question: true,
      guidance: '相手が逆質問している。文脈に沿って，質問に対する回答をしたり，自然な会話をする。',
      priorities: ['相手の質問に対して答える', '質問の範囲を狭めて答えやすくする'],
      dice_hint: 'C',
    });
  }

  if (state.consecutive_questions >= 2) {
    return base({
      should_ask_question: false,
      should_end: false,
      guidance:
        '質問が2回続いている。このターンでは新しい質問や確認を一切せず、対象業務について分かってきたことと、その人の仕事ぶりへの理解を短い平叙文で返す。疑問符で終えない。回答を求めない。',
      priorities: ['ここまでの理解を短く返す', '業務や人柄への関心を自然に示す', '質問しない', '疑問文にしない'],
    });
  }

  if (info.signs_of_resistance.length || info.signs_of_no_information.length) {
    return base({
      should_ask_question: false,
      should_end: false,
      guidance:
        '相手が答えづらそう、または情報が出にくい。無理に深掘りせず、対話履歴に沿った質問をする必要ならここまで分かっていることを短くまとめる。',
      priorities: ['会話の圧を下げる', '質問しない', 'これまでの発話内容を丁寧に見返す', '印象に残ったエピソードや工夫みたいな類の聞きかたはNG'],
    });
  }

  if (state.turns_since_reflection >= 3) {
    return base({
      should_ask_question: false,
      should_end: false,
      guidance:
        'ここまで質問や情報回収が続いている。次は質問せず、分かってきた業務の見え方やその人らしさを返しつつ，適切な質問や相槌を打つ。',
      priorities: ['ここまでの理解を返す', '相手の仕事ぶりへの理解を示す', '質問しない'],
    });
  }

  if (state.task_coverage < 0.7) {
    return base({
      should_ask_question: true,
      should_end: false,
      guidance:
        '対象業務の流れ・場面・仕事の進め方の理解がまだ浅い。ただし『どんな工夫』『具体的に』とは聞かず、相手の直前発話に乗って自然に業務の様子を聞く。CDM／ACTAも参考に．',
      priorities: ['対象業務の様子を理解する', '相手の直前発話に乗る', '質問攻めにしない'],
      dice_hint: 'D',
    });
  }

  if (state.task_depth < 5) {
    return base({
      should_ask_question: true,
      should_end: false,
      guidance:
        '対象業務の表面的な流れは見えてきたが、理由・価値観・本音・経験・源泉はまだ浅い。ここぞという感じで、相手の発話に含まれる意味を自然に深める。既に分かっている理由を聞き直さない。',
      priorities: ['対象業務(target work)についてであることを補足しながら，それにまつわる意味を深める', 'ラポールを意識して、相手の発話に乗る', '仕事観や価値観を自然に探る'],
      dice_hint: 'E',
    });
  }

  if (state.irregular_coverage < 0.7) {
    return base({
      should_ask_question: true,
      should_end: false,
      guidance:
        '対象の業務についてはある程度見えてきた。その対象の業務における，イレギュラーな状況や困った場面があるのか，またどう対処するかに軽く触れる。細かい手順や具体例をしつこく求めない。',
      priorities: ['イレギュラー時の構えを軽く確認する', '深掘りしすぎない', '既に出た価値観を前提にする'],
      dice_hint: 'C',
    });
  }

  if (state.task_depth === 5) {
    return base({
      should_ask_question: true,
      should_end: false,
      guidance:
        '対象業務についてとそれに関する考え方は分かってきた。ここからは、相手の発話に乗りつつ、その考え方を育んだ個人的な考え方やパーソナルな部分により踏み込んでいく既に分かっている理由を聞き直さない。',
      priorities: ['ラポールを意識して、相手の発話に乗る', '考え方を育んだパーソナルな考え方や会社や社会に対する考えを引き出す仕事観や価値観を自然に探る'],
    });
  }

  return base({
    should_ask_question: false,
    should_end: false,
    guidance: '情報は概ね足りている。自然にここまでの理解を返し、終了に向かう。',
    priorities: ['理解を返す', '感謝する'],
  });
}

async function generateUtterance(
  env: RuntimeEnv,
  guide: ConversationGuide,
  state: InterviewState,
  latestAnswer: string,
  chatHistory: MessageRow[],
  workerContext?: WorkerContext,
) {
  const prompt = `あなたは半構造化インタビューを行う自然な聞き手です。

基本姿勢:
「お仕事についてお話を聞かせてください」という姿勢で話してください。
相手の業務や人柄を理解しながら、自然な会話として進めてください。

裏で知りたいこと:
- 対象業務がどのように成り立っているか
- その人が何を見て、何を大事にしているか
- 理由、価値観、本音、経験、源泉
- イレギュラーな状況とその対応

必ず守ること:
- guide に従う。
- 対話履歴(chat_history)を踏まえて、自然な会話として発話する。
- should_ask_question が false の場合は、原則として質問しない。
- should_repair が true の場合は、まず謝り、既に分かっていることを正しく言い直す。
- should_answer_user_question が true の場合は、相手の確認・逆質問に短く答える。
- avoid_reasking に含まれることは絶対に聞き直さない。
- use_as_known に含まれることは既知の前提として使う。
- 対象業務から勝手に離れない。
- 作業員プロフィールと長期記憶は質問の焦点選択と重複回避の参考文脈として使う。毎回引用・言及する必要はなく、過去の話と現在の話を混同しない。
- 過去の未深掘りテーマが直前発話と自然につながる場合は優先してよい。唐突に話題を切り替えない。
${assistantPlaceholderInstruction()}

DICEの使い方:
dice_hint がある場合だけ、裏側で軽く参考にする。
- D: 業務の様子が見える方向
- I: その人自身の経験・立場に戻す方向
- C: 曖昧語を業務文脈に接地する方向
- E: 理由・意味づけ・価値観を深める方向

【conversation guide】
${JSON.stringify(guide)}

【現在の state】
${JSON.stringify(state)}

【作業員プロフィール・長期記憶・過去セッション要約】
${JSON.stringify(workerContext ?? null)}

【対話履歴】
${dumpMessages(chatHistory)}

【直前の回答】
${latestAnswer}

次の自然な発話を生成してください。`;

  const text = await safeOpenaiText(env, prompt);
  const generated = sanitizeAssistantText(text.trim() || fallbackQuestion(state));
  return enforceQuestionPolicy(env, generated, guide);
}

async function enforceQuestionPolicy(env: RuntimeEnv, text: string, guide: ConversationGuide) {
  if (guide.should_ask_question || !isQuestionText(text)) return text;

  const rewritten = sanitizeAssistantText((await safeOpenaiText(
    env,
    `次のインタビュアー発話を、意味を増減させず、相手への理解を返す短い平叙文に書き直してください。
質問、確認、依頼、疑問符、回答を促す表現は禁止です。出力は書き直した発話だけにしてください。

【発話】
${text}`,
  )).trim());

  if (rewritten && !isQuestionText(rewritten)) return rewritten;
  return statementFallback(text);
}

function isQuestionText(text: string) {
  return /[?？]/.test(text) || /(?:ですか|ますか|でしょうか|だろうか|教えてください|聞かせてください)[。.!！\s]*$/.test(text.trim());
}

function statementFallback(text: string) {
  const firstStatement = text.split(/[?？]/, 1)[0].trim();
  if (firstStatement && !isQuestionText(firstStatement)) return `${firstStatement.replace(/[。.!！]+$/, '')}。`;
  return 'ここまでのお話から、状況を確かめながら丁寧に業務を進めていることが伝わってきます。';
}

async function localizeUtterance(env: RuntimeEnv, text: string, language: Language) {
  if (language === 'ja' || !env.OPENAI_API_KEY) return text;
  const translated = await safeOpenaiText(
    env,
    `Translate the following interviewer's utterance into ${languageNames[language]}. Keep it concise, natural, and faithful. Return only the translation.\n\n${text}`,
  );
  return translated.trim() || text;
}

async function safeOpenaiText(env: RuntimeEnv, input: string, options: { json?: boolean; schemaName?: string } = {}) {
  try {
    return await openaiText(env, input, options);
  } catch (error) {
    console.error(error);
    return '';
  }
}

function updateAfterUtterance(state: InterviewState, utterance: string) {
  const text = utterance.trim();
  const isQuestion = text.includes('?') || text.includes('？');

  if (isQuestion) {
    state.consecutive_questions += 1;
    state.turns_since_reflection += 1;
    state.asked_points.push(`過去の質問: ${text}`);
  } else {
    state.consecutive_questions = 0;
    state.turns_since_reflection = 0;
    state.rapport = Math.min(1, state.rapport + 0.04);
  }

  trimState(state);
}

function shouldEndInterview(state: InterviewState) {
  return state.task_coverage >= 1 && state.task_depth >= 6 && state.irregular_coverage >= 1;
}

function buildUseAsKnown(state: InterviewState) {
  const items: string[] = [];
  if (state.target_work) items.push(`対象業務: ${state.target_work}`);
  items.push(...state.known_facts);
  for (const note of state.persona_notes) items.push(`人柄・仕事観メモ: ${note}`);
  return uniqueNonempty(items);
}

function buildAvoidReasking(state: InterviewState) {
  const items = [...state.known_facts, ...state.asked_points];
  if (state.target_work) items.push(`対象業務は ${state.target_work}。別業務へ勝手に移らない。`);
  return uniqueNonempty(items);
}

function uniqueNonempty(items: string[]) {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of items) {
    const value = item.trim();
    if (!value || seen.has(value)) continue;
    seen.add(value);
    result.push(value);
  }
  return result;
}

function hasInformativeContent(info: ExtractedInfo) {
  return Boolean(
    info.target_work ||
      info.situations.length ||
      info.practices.length ||
      info.reasons.length ||
      info.values.length ||
      info.sources.length ||
      info.personal_meanings.length ||
      info.irregular_situations.length ||
      info.irregular_responses.length ||
      info.persona_notes.length ||
      info.emotions.length,
  );
}

function trimState(state: InterviewState) {
  state.known_facts = state.known_facts.slice(-30);
  state.asked_points = state.asked_points.slice(-30);
  state.persona_notes = state.persona_notes.slice(-20);
}

function dumpMessages(messages: MessageRow[]) {
  return messages.map((message) => `${message.role}: ${message.content}`).join('\n');
}

function fallbackExtract(text: string): ExtractedInfo {
  const lower = text.toLowerCase();
  return {
    ...emptyExtraction,
    target_work: text.length > 4 ? text.slice(0, 80) : null,
    practices: text.length > 8 ? [text.slice(0, 160)] : [],
    signs_of_no_information: /特になし|わからない|分からない|nothing|none|weiß nicht/.test(lower) ? [text] : [],
    wants_to_stop: /終了|終わり|stop|end|quit|beenden/.test(lower),
  };
}

function fallbackQuestion(state: InterviewState) {
  if (!state.target_work) return '先ほどの業務について、その時の状況も含めてもう少し聞かせてください。';
  const target = sanitizeAssistantText(state.target_work);
  if (state.task_coverage < 0.7) return `${target} の場面では、普段どんな流れで進めていましたか？`;
  if (state.task_depth < 5) return `その ${target} で大事にしている判断や考え方はありますか？`;
  return `${target} で想定外のことが起きた時は、どのように受け止めていますか？`;
}
