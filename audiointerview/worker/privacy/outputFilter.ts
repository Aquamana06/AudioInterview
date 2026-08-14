import { maskingPolicy, placeholderExamples } from './maskingPolicy.js';

export function sanitizeAssistantText(text: string) {
  return text.replace(/<([A-Z_]+)_[A-Z]+>/g, (_match, category: string) => {
    return maskingPolicy[category as keyof typeof maskingPolicy] ?? 'その対象';
  });
}

export function placeholderCorrectionInstruction() {
  return `\n\n機密情報保護:\n- <TANK_A>、<REACTOR_A>、<CHEMICAL_A>、<PROCESS_A> 等は、企業固有情報を匿名化した内部識別子です。\n- placeholderの実体を推測してはいけません。\n- placeholderを変更・削除・展開してはいけません。\n- 化学プラントの一般的な文脈を参考に、placeholder以外の明らかな音声認識誤りのみ修正してください。`;
}

export function assistantPlaceholderInstruction() {
  const examples = placeholderExamples.slice(0, 6).join('、');
  const labels = Object.values(maskingPolicy).slice(0, 6).join('」「');
  return `\n\n機密情報保護:\n- 対話履歴やstateにある ${examples} などのplaceholderは、企業固有情報を匿名化した内部識別子です。\n- placeholderの実体を推測してはいけません。\n- placeholderをユーザーへの発話にそのまま含めてはいけません。\n- 必要な場合は「${labels}」のような自然な一般表現で話してください。`;
}
