const corrections: Array<[RegExp, string]> = [
  [/ぴーぴーいー|ＰＰＥ|pp[eE]|P P E/gi, 'PPE'],
  [/(けんか|ケンカ|けん化)(?=剤|反応|工程|処理|価|$|[、。])/g, '鹸化'],
  [/(じゅうごう|ジュウゴウ|重合う|15)(?=反応|度|工程|槽|物|樹脂|$|[、。])/g, '重合'],
]

const maskRules: Array<[RegExp, string]> = [
  [/苛性ソーダ/g, '[薬品B]'],
  [/塩酸/g, '[薬品A]'],
  [/トルエン/g, '[薬品C]'],
]

export function prepareLocalTranscript(input: string): { normalizedText: string; maskedText: string } {
  const normalizedText = corrections.reduce((text, [pattern, replacement]) => text.replace(pattern, replacement), input)
  const maskedText = maskRules.reduce((text, [pattern, replacement]) => text.replace(pattern, replacement), normalizedText)
  return { normalizedText, maskedText }
}
