import { openaiText } from './openai.js';
import type { MessageRow, RuntimeEnv } from './types.js';
import type { ParticipantProfile } from './longitudinal-types.js';

export interface ProfileTurnExtraction {
  role: string[];
  position_or_seniority: string[];
  experience: string[];
  responsibilities: string[];
  typical_day: string[];
  collaborators: string[];
  workplace_context: string[];
  personally_important_topics: string[];
  other_personal_context: string[];
  signs_of_discomfort: string[];
  signs_of_no_information: string[];
  wants_to_stop: boolean;
}

export const emptyProfileExtraction = (): ProfileTurnExtraction => ({
  role: [],
  position_or_seniority: [],
  experience: [],
  responsibilities: [],
  typical_day: [],
  collaborators: [],
  workplace_context: [],
  personally_important_topics: [],
  other_personal_context: [],
  signs_of_discomfort: [],
  signs_of_no_information: [],
  wants_to_stop: false,
});

function strings(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string').map((item) => item.trim()).filter(Boolean) : [];
}

function parseObject(text: string) {
  const cleaned = text.trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '');
  return JSON.parse(cleaned) as Record<string, unknown>;
}

function dump(messages: MessageRow[]) {
  return messages.map((message) => `${message.role}: ${message.content}`).join('\n');
}

export async function extractProfileTurn(
  env: RuntimeEnv,
  userInput: string,
  history: MessageRow[],
  knownProfile: ParticipantProfile,
): Promise<ProfileTurnExtraction> {
  const prompt = `あなたは初回インタビュー専用の情報抽出エージェントです。
直前の参加者発話を会話履歴に沿って読み、仕事の全体像に関する情報を抽出してください。

規則:
- 本人が話していないことを推測しない。
- 同じ内容を複数項目へ安易に重複させない。
- 肩書きがなくても、実際の立場や熟練度が語られれば position_or_seniority に入れる。
- personally_important_topics は本人が自然に強調した、今後の会話で大切に扱うべき話題だけにする。
- 答えづらさ、拒否、終了希望を見落とさない。
- JSONだけを返す。

出力形式:
{"role":[],"position_or_seniority":[],"experience":[],"responsibilities":[],"typical_day":[],"collaborators":[],"workplace_context":[],"personally_important_topics":[],"other_personal_context":[],"signs_of_discomfort":[],"signs_of_no_information":[],"wants_to_stop":false}

保存済みプロフィール:
${JSON.stringify(knownProfile)}

今回の会話:
${dump(history)}

直前の参加者発話:
${userInput}`;
  try {
    const raw = parseObject(await openaiText(env, prompt));
    return {
      role: strings(raw.role),
      position_or_seniority: strings(raw.position_or_seniority),
      experience: strings(raw.experience),
      responsibilities: strings(raw.responsibilities),
      typical_day: strings(raw.typical_day),
      collaborators: strings(raw.collaborators),
      workplace_context: strings(raw.workplace_context),
      personally_important_topics: strings(raw.personally_important_topics),
      other_personal_context: strings(raw.other_personal_context),
      signs_of_discomfort: strings(raw.signs_of_discomfort),
      signs_of_no_information: strings(raw.signs_of_no_information),
      wants_to_stop: raw.wants_to_stop === true,
    };
  } catch (error) {
    console.error('Failed to extract first-session profile information', error);
    return emptyProfileExtraction();
  }
}
