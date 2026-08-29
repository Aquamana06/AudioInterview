import { env, pipeline } from '@huggingface/transformers'

type PromptTokenizer = {
  get_prompt_ids?: (text: string, options?: { return_tensors?: string }) => unknown
}

type WhisperPipeline = {
  tokenizer: PromptTokenizer
  (audio: Float32Array, options: Record<string, unknown>): Promise<{ text?: string; chunks?: Array<{ text: string }> }>
}

const PROMPT = '化学プラントの現場インタビュー。専門用語: 重合、鹸化、加水分解、触媒、モノマー、ポリマー。読み方: じゅうごう、けんか。'

let transcriberPromise: Promise<WhisperPipeline> | null = null

function canUseWebGPU(): boolean {
  return typeof navigator !== 'undefined' && 'gpu' in navigator
}

type WebGPUNavigator = Navigator & {
  gpu?: { requestAdapter: () => Promise<unknown> }
}

function modelId(): string {
  // Use the larger model for better Japanese and technical-vocabulary
  // recognition. This increases initial download and browser GPU/memory load.
  return 'onnx-community/whisper-small'
}

async function getTranscriber(onProgress?: (message: string) => void): Promise<WhisperPipeline> {
  const gpu = (typeof navigator !== 'undefined' ? navigator : undefined) as WebGPUNavigator | undefined
  console.info('[AudioInterview][Whisper] WebGPU check', {
    userAgent: navigator.userAgent,
    secureContext: window.isSecureContext,
    hasNavigatorGpu: canUseWebGPU(),
  })
  if (!canUseWebGPU()) throw new Error('このブラウザはWebGPUに対応していません（navigator.gpuがありません）')
  const adapter = await gpu?.gpu?.requestAdapter()
  console.info('[AudioInterview][Whisper] GPU adapter', adapter)
  if (!adapter) throw new Error('WebGPUのGPUアダプターを取得できません')
  if (!transcriberPromise) {
    onProgress?.('Whisperモデルを読み込んでいます（WebGPU、初回のみ時間がかかります）…')
    // Fetch model files through the Worker so deployed sites do not depend on
    // Hugging Face returning CORS headers for every redirected asset.
    env.remoteHost = `${window.location.origin}/api/models`
    // The library appends the requested filename after this template.
    // Keep the Hub's resolve endpoint so large ONNX files are served as the
    // original binary rather than as a raw repository response.
    env.remotePathTemplate = '{model}/resolve/{revision}/'
    console.info('[AudioInterview][Whisper] loading model', modelId())
    transcriberPromise = pipeline('automatic-speech-recognition', modelId(), {
      device: 'webgpu',
      dtype: 'q4',
      progress_callback: (event: { status?: string; file?: string; progress?: number }) => {
        console.info('[AudioInterview][Whisper] progress', event)
        if (event.status === 'progress' && typeof event.progress === 'number') {
          onProgress?.(`Whisperモデルを読み込み中… ${Math.round(event.progress)}%`)
        } else if (event.status === 'ready' || event.status === 'done') {
          onProgress?.('モデルのダウンロード完了。Whisperを初期化しています…')
        }
      },
    }) as unknown as Promise<WhisperPipeline>
    transcriberPromise.catch(error => console.error('[AudioInterview][Whisper] model load failed', error))
  }
  return transcriberPromise
}

function audioContext(): AudioContext {
  return new AudioContext()
}

async function blobToMonoFloat32(blob: Blob): Promise<Float32Array> {
  const context = audioContext()
  try {
    const decoded = await context.decodeAudioData(await blob.arrayBuffer())
    const mono = new Float32Array(decoded.length)
    for (let c = 0; c < decoded.numberOfChannels; c += 1) {
      const source = decoded.getChannelData(c)
      for (let i = 0; i < source.length; i += 1) mono[i] += source[i] / decoded.numberOfChannels
    }
    // Whisper's feature extractor expects 16 kHz PCM. MediaRecorder usually
    // produces 44.1/48 kHz audio, so resample before passing it to the model.
    const targetRate = 16000
    if (decoded.sampleRate === targetRate) return mono
    const targetLength = Math.max(1, Math.round(mono.length * targetRate / decoded.sampleRate))
    const resampled = new Float32Array(targetLength)
    const ratio = decoded.sampleRate / targetRate
    for (let i = 0; i < targetLength; i += 1) {
      const sourcePosition = i * ratio
      const left = Math.floor(sourcePosition)
      const right = Math.min(left + 1, mono.length - 1)
      const fraction = sourcePosition - left
      resampled[i] = mono[left] * (1 - fraction) + mono[right] * fraction
    }
    return resampled
  } finally {
    await context.close()
  }
}

export async function transcribeInBrowser(
  blob: Blob,
  language: string,
  onProgress?: (message: string) => void,
  includePrompt = true,
): Promise<{ rawText: string; chunks?: Array<{ text: string; timestamp?: [number, number] }> }> {
  const transcriber = await getTranscriber(onProgress)
  const audio = await blobToMonoFloat32(blob)
  const promptIds = transcriber.tokenizer.get_prompt_ids?.(PROMPT, { return_tensors: 'np' })
  const result = await transcriber(audio, {
    language,
    task: 'transcribe',
    ...(includePrompt && promptIds ? { generate_kwargs: { prompt_ids: promptIds } } : {}),
  })
  return { rawText: result.text?.trim() ?? '', chunks: result.chunks }
}

function pcmToWav(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)
  const write = (offset: number, value: string) => { for (let i = 0; i < value.length; i += 1) view.setUint8(offset + i, value.charCodeAt(i)) }
  write(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true); write(8, 'WAVE')
  write(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true)
  write(36, 'data'); view.setUint32(40, samples.length * 2, true)
  for (let i = 0; i < samples.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(44 + i * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true)
  }
  return new Blob([buffer], { type: 'audio/wav' })
}

export async function detectOverInBrowser(samples: Float32Array, sampleRate: number, language: string): Promise<boolean> {
  const result = await transcribeInBrowser(pcmToWav(samples, sampleRate), language, undefined, false)
  const text = result.rawText.toLowerCase().replace(/[.,!?。、！？]/g, '').replace(/\s+/g, '')
  return /(?:\bover\b|オーバー|オーバ|おーばー|おおばー)/i.test(text)
}

export async function preloadBrowserWhisper(onProgress?: (message: string) => void): Promise<void> {
  await getTranscriber(onProgress)
}

export function resetBrowserWhisper(): void {
  transcriberPromise = null
}
