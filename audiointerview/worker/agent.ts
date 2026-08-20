import { emptyExtraction, openaiText } from './openai.js';
import type { AgentResult, ConversationGuide, ExtractedInfo, InterviewState, Language, MessageRow, RuntimeEnv } from './types.js';

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
): Promise<AgentResult> {
  const extracted = await extractInfo(env, userInput, state, chatHistory);
  const nextState = updateStateFromExtraction(structuredClone(state), extracted);
  const guide = buildConversationGuide(nextState, extracted);

  if (extracted.wants_to_stop || guide.should_end) {
    return {
      text: endings[language],
      state: nextState,
      stateLabel: 'end',
      extracted,
      guide,
    };
  }

  const generated = await generateUtterance(env, guide, nextState, userInput, chatHistory);
  const localized = await localizeUtterance(env, generated, language);
  updateAfterUtterance(nextState, localized);

  return {
    text: localized,
    state: nextState,
    stateLabel: 'running',
    extracted,
    guide,
  };
}

async function extractInfo(env: RuntimeEnv, userInput: string, state: InterviewState, chatHistory: MessageRow[]) {
  const prompt = `あなたは半構造化インタビューの情報抽出器です。
直前のインタビュイ発話から、対象業務に関する情報を構造化してください。

重要:
- キーワード一致ではなく、対話の流れで判断する。
- 想像で補わない。
- 抽象的・一般的な表現を、深さの根拠として過大評価しない。
- reasons は、具体的な実践や判断と「なぜ」が明示的に結び付いている場合だけ抽出する。
- sources は、経験・教育・他者からの教えなど、考え方の形成源が具体的に語られた場合だけ抽出する。
- values は、単なる好みや感想ではなく、業務で優先する判断基準・信念が明示された場合だけ抽出する。
- personal_meanings は、個人的な経験と現在の仕事観のつながり、または本人にとっての仕事の意味が明示された場合だけ抽出する。
- 同じ一文を複数の深さ項目へ安易に重複分類しない。判断に迷う場合は抽出しない。
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

【現在の state】
${JSON.stringify(state)}

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
  }

  for (const item of info.reasons) state.known_facts.push(`理由: ${item}`);

  for (const item of info.sources) state.known_facts.push(`源泉: ${item}`);

  for (const item of info.values) state.known_facts.push(`価値観: ${item}`);

  for (const item of info.personal_meanings) state.known_facts.push(`個人的意味・価値観の形成背景・真髄: ${item}`);

  // Depth is earned only when the evidence forms a contiguous chain. A single
  // abstract value or personal anecdote must not skip the missing layers.
  state.task_depth = Math.max(state.task_depth, calculateSupportedDepth(state));

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
        '質問が続いている。仕事に対する姿勢を知れるようなその業務やその人にまつわる軽い質問または確認をする対象業務について分かってきたことを短く言語化して確認する',
      priorities: ['理解を返す(？で終わってもいい)', '業務や人柄への関心を自然に示す'],
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
        '対象業務の流れ・場面・仕事の進め方の理解がまだ浅い。ただし『どんな工夫』『具体的に』とは聞かず、相手の直前発話に乗って自然に業務の様子を聞く。',
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
- 発話は短い1〜2文に収める。前置きや説明を重ねない。
- 質問する場合は、一度に一つだけ尋ねる。複数の疑問文や質問項目を並べない。
- 相手の発話の要約は、質問に必要な最小限の一節だけにする。
- should_ask_question が false の場合は、原則として質問しない。
- should_repair が true の場合は、まず謝り、既に分かっていることを正しく言い直す。
- should_answer_user_question が true の場合は、相手の確認・逆質問に短く答える。
- avoid_reasking に含まれることは絶対に聞き直さない。
- use_as_known に含まれることは既知の前提として使う。
- 対象業務から勝手に離れない。

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

【対話履歴】
${dumpMessages(chatHistory)}

【直前の回答】
${latestAnswer}

次の自然でコンパクトな発話だけを生成してください。解説やラベルは付けないでください。`;

  const text = await safeOpenaiText(env, prompt);
  return text.trim() || fallbackQuestion(state);
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

function calculateSupportedDepth(state: InterviewState) {
  if (!state.target_work) return 0;

  const has = (prefix: string) => state.known_facts.some((fact) => fact.startsWith(prefix));
  if (!has('業務上の実践:')) return 1;
  if (!has('理由:')) return 2;
  if (!has('源泉:')) return 3;
  if (!has('価値観:')) return 4;
  if (!has('個人的意味・価値観の形成背景・真髄:')) return 5;
  return 6;
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
  if (state.task_coverage < 0.7) return `${state.target_work} の場面では、普段どんな流れで進めていましたか？`;
  if (state.task_depth < 5) return `その ${state.target_work} で大事にしている判断や考え方はありますか？`;
  return `${state.target_work} で想定外のことが起きた時は、どのように受け止めていますか？`;
}
