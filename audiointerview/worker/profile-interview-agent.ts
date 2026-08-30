import { endings } from './agent.js';
import { emptyExtraction, openaiText } from './openai.js';
import type { AgentResult, InterviewState, Language, MessageRow, RuntimeEnv } from './types.js';
import type { ParticipantProfile } from './longitudinal-types.js';
import { emptyProfileExtraction, extractProfileTurn } from './profile-interview-openai.js';
import type { ProfileTurnExtraction } from './profile-interview-openai.js';

export type ProfileInterviewResult = AgentResult & { profileExtraction: ProfileTurnExtraction };

const fallbackOpenings: Record<Language, string> = {
  ja: '最初に、普段どんな立場でお仕事をされているのか、差し支えない範囲で教えていただけますか？',
  en: 'To start, could you tell me a little about your usual role at work, as far as you are comfortable sharing?',
  de: 'Erzählen Sie mir zu Beginn bitte, soweit es für Sie in Ordnung ist, etwas über Ihre übliche Rolle bei der Arbeit.',
};

function dump(messages: MessageRow[]) {
  return messages.map((message) => `${message.role}: ${message.content}`).join('\n');
}

export async function generateProfileInterviewStarter(env: RuntimeEnv, language: Language) {
  if (!env.OPENAI_API_KEY) return fallbackOpenings[language];
  const languageName = language === 'ja' ? '日本語' : language === 'en' ? '英語' : 'ドイツ語';
  const prompt = `初対面の参加者との第1回インタビューを始める、短く自然な発話を${languageName}で1〜2文生成してください。
目的は、安心して話せる雰囲気を作り、差し支えない範囲で現在の担当や立場を尋ねることです。
尋問調にせず、一度に一つだけ尋ねてください。「プロフィール収集」「信頼関係」という分析用語は使わず、発話だけを返してください。`;
  try {
    return (await openaiText(env, prompt)).trim() || fallbackOpenings[language];
  } catch (error) {
    console.error('Failed to generate profile interview starter', error);
    return fallbackOpenings[language];
  }
}

export async function runProfileInterviewTurn(
  env: RuntimeEnv,
  state: InterviewState,
  userInput: string,
  history: MessageRow[],
  language: Language,
  knownProfile: ParticipantProfile,
): Promise<ProfileInterviewResult> {
  const nextState = structuredClone(state);
  nextState.turn_count += 1;
  const extracted = env.OPENAI_API_KEY
    ? await extractProfileTurn(env, userInput, history, knownProfile)
    : emptyProfileExtraction();
  for (const [key, values] of Object.entries(extracted)) {
    if (!Array.isArray(values)) continue;
    for (const value of values) nextState.persona_notes.push(`初回プロフィール/${key}: ${value}`);
  }
  const knownGroups = new Set(nextState.persona_notes.map((note) => note.match(/^初回プロフィール\/([^:]+):/)?.[1]).filter(Boolean));
  const coverage = knownGroups.size;
  const wantsToStop = extracted.wants_to_stop || /終了|終わり|やめ|stop|quit|end|beenden/i.test(userInput);
  const shouldEnd = wantsToStop || nextState.turn_count >= 9 || (nextState.turn_count >= 5 && coverage >= 5);
  if (shouldEnd) {
    return {
      text: endings[language],
      state: nextState,
      stateLabel: 'end',
      extracted: { ...emptyExtraction, wants_to_stop: wantsToStop },
      guide: {
        should_ask_question: false,
        should_end: true,
        guidance: '初回の基本的な理解が得られたため、感謝して終了する。',
        priorities: ['感謝して終了する'],
        avoid_reasking: [],
        use_as_known: [],
      },
      profileExtraction: extracted,
    };
  }

  const languageName = language === 'ja' ? '日本語' : language === 'en' ? '英語' : 'ドイツ語';
  const prompt = `あなたは初回の半構造化インタビューを行う、親しみのある自然な聞き手です。${languageName}で次の発話だけを生成してください。

今回だけの目的:
- 参加者と無理のない雑談的な関係を作り、仕事をしている姿が少しずつ浮かぶ会話にする。
- 差し支えない範囲で、担当、役割・役職、経験年数や熟練度、普段の責任範囲、一日の大まかな流れ、関わる人を理解する。
- 性格を決めつけず、本人の言葉で基本的な仕事上のプロフィールを知る。

規則:
- 直前の回答に、短い相槌、共感、関心、または理解の言い返しで応じる。その応答は回答内容に即したものにする。
- その流れから、まだ十分に分かっていない全体像を一つだけ尋ねる。
- 質問票のように項目を列挙しない。短い1〜2文にする。
- 「役職は？」「経験年数は？」のような項目名だけの直球質問を連続させない。本人が話した内容を足場に言い換える。
- 毎回同じ「なるほど」「そうなんですね」だけで始めない。
- 答えたくない内容は無理に聞かない。「差し支えない範囲で」という姿勢を保つ。
- この初回では調整行動や価値観を深掘りしない。参加者が自発的に話した場合は受け止めるだけにする。
- すでに答えたことを聞き直さない。
- 解説やラベルを付けない。

現在保存されているプロフィール:
${JSON.stringify(knownProfile)}

このターンまでに分かった初回プロフィール:
${JSON.stringify(nextState.persona_notes)}

直前発話からの抽出結果:
${JSON.stringify(extracted)}

まだ情報が少ない領域を内部で一つ選び、直前の話から最も自然につながるものだけを聞いてください。網羅順に聞く必要はありません。

今回の会話:
${dump(history)}

直前の回答:
${userInput}`;
  let text = '';
  try {
    text = (await openaiText(env, prompt)).trim();
  } catch (error) {
    console.error('Failed to run profile interview turn', error);
  }
  if (!text) text = language === 'ja' ? '普段は、どのくらいの期間そのお仕事をされているんですか？' : fallbackOpenings[language];
  nextState.consecutive_questions += 1;
  nextState.turns_since_reflection += 1;
  return {
    text,
    state: nextState,
    stateLabel: 'running',
    extracted: emptyExtraction,
    guide: {
      should_ask_question: true,
      should_end: false,
      guidance: '初回のプロフィール形成を、雑談的で答えやすい一問として進める。',
      priorities: ['回答を受け止める', '未確認の基本情報を一つだけ聞く', '深掘りしすぎない'],
      avoid_reasking: [],
      use_as_known: [],
    },
    profileExtraction: extracted,
  };
}
