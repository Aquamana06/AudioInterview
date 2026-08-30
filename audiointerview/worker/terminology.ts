/** Domain hints and the final, deterministic privacy boundary. */
export const transcriptionPrompt =
  '化学プラントの現場インタビュー。専門用語の表記を優先: PPE、鹸化、重合。' +
  '誤認識候補: ぴーぴーいー→PPE、けんか→鹸化、じゅうごう/15→重合。';

const corrections: Array<[RegExp, string]> = [
  [/ぴーぴーいー|ＰＰＥ|pp[eE]|P P E/gi, 'PPE'],
  [/(けんか|ケンカ|けん化)(?=剤|反応|工程|処理|価|$|[、。])/g, '鹸化'],
  [/(じゅうごう|ジュウゴウ|重合う|15)(?=反応|度|工程|槽|物|樹脂|$|[、。])/g, '重合'],
];

// Sample rules. Replace these with the plant's confidential chemical names.
const maskRules: Array<[string, string]> = [
  ['苛性ソーダ', '薬品B'],
  ['塩酸', '薬品A'],
  ['トルエン', '薬品C'],
];

export function normalizeTechnicalTerms(input: string): string {
  return corrections.reduce((text, [pattern, replacement]) => text.replace(pattern, replacement), input);
}

export function maskConfidentialTerms(input: string): string {
  return maskRules.reduce((text, [term, replacement]) => text.replaceAll(term, replacement), input);
}

export function prepareForCloudLlm(input: string): { normalizedText: string; maskedText: string } {
  const normalizedText = normalizeTechnicalTerms(input);
  return { normalizedText, maskedText: maskConfidentialTerms(normalizedText) };
}
