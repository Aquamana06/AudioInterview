export const maskingPolicy = {
  TANK: 'そのタンク',
  LEVEL_SENSOR: 'その液面計',
  REACTOR: 'その反応器',
  CATALYST: 'その触媒',
  PRODUCT: 'その製品',
  PURIFICATION_PROCESS: 'その精製工程',
  CHEMICAL: 'その薬品',
  PROCESS: 'その工程',
  EQUIPMENT: 'その設備',
} as const;

export const placeholderExamples = Object.keys(maskingPolicy).map((category) => `<${category}_A>`);
