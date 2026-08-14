import type { ExtractedInfo, RuntimeEnv } from './types.js';

type ResponseMessage = {
  output?: Array<{ content?: Array<{ type: string; text?: string }> }>;
  output_text?: string;
};

const extractionSchema = {
  type: 'object',
  additionalProperties: false,
  properties: {
    target_work: { type: ['string', 'null'] },
    situations: { type: 'array', items: { type: 'string' } },
    practices: { type: 'array', items: { type: 'string' } },
    reasons: { type: 'array', items: { type: 'string' } },
    values: { type: 'array', items: { type: 'string' } },
    sources: { type: 'array', items: { type: 'string' } },
    personal_meanings: { type: 'array', items: { type: 'string' } },
    irregular_situations: { type: 'array', items: { type: 'string' } },
    irregular_responses: { type: 'array', items: { type: 'string' } },
    persona_notes: { type: 'array', items: { type: 'string' } },
    emotions: { type: 'array', items: { type: 'string' } },
    user_questions: { type: 'array', items: { type: 'string' } },
    signs_of_friction: { type: 'array', items: { type: 'string' } },
    signs_of_resistance: { type: 'array', items: { type: 'string' } },
    signs_of_no_information: { type: 'array', items: { type: 'string' } },
    wants_to_stop: { type: 'boolean' },
  },
  required: [
    'target_work',
    'situations',
    'practices',
    'reasons',
    'values',
    'sources',
    'personal_meanings',
    'irregular_situations',
    'irregular_responses',
    'persona_notes',
    'emotions',
    'user_questions',
    'signs_of_friction',
    'signs_of_resistance',
    'signs_of_no_information',
    'wants_to_stop',
  ],
};

export const emptyExtraction: ExtractedInfo = {
  target_work: null,
  situations: [],
  practices: [],
  reasons: [],
  values: [],
  sources: [],
  personal_meanings: [],
  irregular_situations: [],
  irregular_responses: [],
  persona_notes: [],
  emotions: [],
  user_questions: [],
  signs_of_friction: [],
  signs_of_resistance: [],
  signs_of_no_information: [],
  wants_to_stop: false,
};

export function outputText(payload: ResponseMessage) {
  if (typeof payload.output_text === 'string') return payload.output_text;
  for (const item of payload.output ?? []) {
    for (const part of item.content ?? []) {
      if (part.type === 'output_text' && part.text) return part.text;
    }
  }
  return '';
}

export async function openaiText(env: RuntimeEnv, input: string, options: { json?: boolean; schemaName?: string } = {}) {
  if (!env.OPENAI_API_KEY) throw new Error('OPENAI_API_KEY is not configured');

  const text = options.json
    ? {
        format: {
          type: 'json_schema',
          name: options.schemaName ?? 'structured_response',
          schema: extractionSchema,
          strict: true,
        },
      }
    : { format: { type: 'text' } };

  const response = await fetch('https://api.openai.com/v1/responses', {
    method: 'POST',
    headers: {
      authorization: `Bearer ${env.OPENAI_API_KEY}`,
      'content-type': 'application/json',
    },
    body: JSON.stringify({
      model: env.OPENAI_TEXT_MODEL ?? 'gpt-5.5',
      input,
      text,
      store: false,
    }),
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`OpenAI request failed: ${response.status} ${body}`);
  }

  return outputText((await response.json()) as ResponseMessage);
}

export async function openaiStatus(env: RuntimeEnv) {
  return {
    configured: Boolean(env.OPENAI_API_KEY),
    textModel: env.OPENAI_TEXT_MODEL ?? 'gpt-5.5',
    transcriptionModel: 'local faster-whisper large-v3',
  };
}
