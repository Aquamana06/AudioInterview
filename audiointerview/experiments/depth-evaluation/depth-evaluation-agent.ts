import { extractInfoForEvaluation, updateStateFromExtractionForEvaluation, endings } from '../../worker/agent.js';
import { openaiText } from '../../worker/openai.js';
import type { AgentResult, InterviewState, Language, MessageRow, RuntimeEnv } from '../../worker/types.js';

export async function runDepthEvaluationTurn(
  env: RuntimeEnv,
  state: InterviewState,
  userInput: string,
  history: MessageRow[],
  language: Language,
  highDepthCount: number,
): Promise<AgentResult & { highDepthCount: number }> {
  const extracted = await extractInfoForEvaluation(env, userInput, state, history);
  const nextState = updateStateFromExtractionForEvaluation(structuredClone(state), extracted);
  const nextHighDepthCount = highDepthCount + (nextState.task_depth >= 5 ? 1 : 0);
  const shouldEnd = extracted.wants_to_stop || nextHighDepthCount >= 2;

  if (shouldEnd) {
    return {
      text: endings[language],
      state: nextState,
      stateLabel: 'end',
      extracted,
      guide: {
        should_ask_question: false,
        should_end: true,
        guidance: extracted.wants_to_stop ? '参加者の終了希望を受けて終了する。' : 'depth 5以上の回答が2回観測されたため終了する。',
        priorities: ['感謝して終了する'],
        avoid_reasking: [],
        use_as_known: [],
      },
      highDepthCount: nextHighDepthCount,
    };
  }

  const prompt = `あなたは半構造化インタビューを行う、自然で柔軟な聞き手です。
参加者の直前の発話を受け止め、その人が話したいことを尊重しながら、仕事や経験について会話を続けてください。

方針:
- 質問の方向や深さをあらかじめ決めつけない。直前の発話と会話全体から、自然に続く一つの関心を選ぶ。
- 必要なら質問するが、質問しないで短く受け止めるだけでもよい。
- 質問する場合は一度に一つだけにする。
- すでに話された内容を機械的に聞き直さない。
- 相手が答えづらそうなら、無理に掘り下げない。
- 分析用語、depthの数値、抽出項目名、インタビューの目的は発話に出さない。
- 短い1〜2文の発話だけを返す。

現在の会話状態:
${JSON.stringify(nextState)}

会話履歴:
${history.map((message) => `${message.role}: ${message.content}`).join('\n')}

直前の参加者発話:
${userInput}

次のインタビュアー発話だけを返してください。`;

  let text = '';
  if (env.OPENAI_API_KEY) {
    try { text = (await openaiText(env, prompt)).trim(); } catch (error) { console.error('Failed to generate evaluation utterance', error); }
  }
  if (!text) text = fallbackQuestion(nextState, language);
  return {
    text,
    state: nextState,
    stateLabel: 'running',
    extracted,
    guide: {
      should_ask_question: true,
      should_end: false,
      guidance: '直前の発話から自然に続く半構造化インタビューを行う。質問の方向は固定しない。',
      priorities: ['発話を受け止める', '会話の文脈に沿って柔軟に続ける'],
      avoid_reasking: [],
      use_as_known: nextState.known_facts,
    },
    highDepthCount: nextHighDepthCount,
  };
}

function fallbackQuestion(state: InterviewState, language: Language) {
  if (language === 'en') return state.target_work ? `What stands out to you about that work?` : 'Could you tell me a little more about that work?';
  if (language === 'de') return state.target_work ? 'Was fällt Ihnen an dieser Arbeit besonders auf?' : 'Können Sie mir etwas mehr über diese Arbeit erzählen?';
  return state.target_work ? 'そのお仕事について、特に印象に残っていることはありますか？' : 'そのお仕事について、もう少し聞かせていただけますか？';
}
