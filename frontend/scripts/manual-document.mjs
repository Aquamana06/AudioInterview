import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { manualContent } from '../src/manualContent.ts'

const escape = value => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;')

export async function manualDocument(directory) {
  const patternPages = await Promise.all(manualContent.patterns.map(async (pattern, patternIndex) => {
    const cards = await Promise.all(pattern.steps.map(async (step, index) => {
      const png = await readFile(path.join(directory, path.basename(step.image)))
      const buttonImage = 'buttonImage' in step
        ? `<img class="button-example" src="data:image/png;base64,${(await readFile(path.join(directory, path.basename(step.buttonImage)))).toString('base64')}" alt="${escape(step.buttonAlt)}">`
        : ''
      return `<section class="screen-card"><h2><b>${index + 1}</b>${escape(step.title)}</h2><p class="key-point">${escape(step.keyPoint)}</p><img src="data:image/png;base64,${png.toString('base64')}" alt="${escape(step.alt)}"><p>${escape(step.text)}</p>${step.note ? `<p class="note">${escape(step.note)}</p>` : ''}${buttonImage}</section>`
    }))
    return `<article class="print-page"><p class="eyebrow">AudioInterview / ${escape(pattern.title)}　${patternIndex + 2} / 6</p><h1>${escape(pattern.title)}</h1><main class="steps">${cards.join('')}</main><p class="caption">画面は操作説明用のサンプルです。上部の状態表示から下部の操作欄までを掲載しています。</p></article>`
  }))
  const { preparation, repeat, questions } = manualContent
  const login = await readFile(path.join(directory, path.basename(preparation.image)))
  let illustration = ''
  if (repeat.image) {
    const extension = path.extname(repeat.image).toLowerCase()
    const mime = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.svg': 'image/svg+xml' }[extension]
    if (!mime) throw new Error(`Unsupported manual illustration format: ${extension}`)
    const image = await readFile(path.join(directory, path.basename(repeat.image)))
    illustration = `<img class="work-illustration" src="data:${mime};base64,${image.toString('base64')}" alt="${escape(repeat.imageAlt)}">`
  }
  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>インタビュー操作マニュアル</title><style>
    @page { size: A4; margin: 13mm 14mm; }
    * { box-sizing: border-box; } body { margin: 0; color: #263d37; font-family: "Noto Sans CJK JP", sans-serif; font-size: 9pt; line-height: 1.8; }
    .print-page { break-after: page; } .print-page:last-child { break-after: auto; }
    .eyebrow { margin: 0; color: #477461; font-size: 8pt; letter-spacing: .6px; } h1 { margin: 3px 0 9px; font-size: 21pt; line-height: 1.4; } h2 { margin: 0 0 10px; font-size: 13pt; }
    .intro { margin: 0 0 13px; }
    .steps { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
    .screen-card { break-inside: avoid; padding: 9px; font-size: 8pt; border: 1px solid #d8e2db; border-radius: 10px; } .screen-card h2 { display: flex; align-items: center; gap: 7px; font-size: 9pt; line-height: 1.6; }
    .screen-card h2 b { display: inline-grid; flex-shrink: 0; place-items: center; width: 23px; height: 23px; border-radius: 50%; color: white; background: #3d7d70; font-size: 10pt; }
    .key-point { margin: 0 0 10px; padding: 6px 8px; border-radius: 5px; color: #245d4e; background: #edf5ef; font-weight: 700; font-size: 8pt; }
    .screen-card img { display: block; width: 45mm; max-width: 100%; height: auto; margin: 0 auto; border: 1px solid #e2e2d8; border-radius: 6px; }
    .screen-card .button-example { width: auto; max-width: 100%; margin-top: 9px; border: 0; border-radius: 0; }
    p { margin: 9px 0 0; } .note { color: #526a5f; font-size: 8pt; }
    .repeat-box { margin-top: 16px; padding: 14px; border: 1px solid #cbded2; border-radius: 9px; background: #f0f6ef; }
    .repeat-cycle { padding: 10px; border-radius: 7px; color: #245d4e; background: white; font-weight: 700; }
    .repeat-text { font-size: 10pt; }
    .work-illustration { display: block; width: 100%; max-height: 155px; margin: 12px auto; object-fit: contain; }
    .faq { margin-top: 20px; } .qa { break-inside: avoid; margin: 9px 0; padding: 11px 14px; border: 1px solid #d8e2db; border-radius: 8px; }
    h3 { margin: 0; color: #315d50; font-size: 10pt; } .qa p { margin-top: 6px; } .qa ol { margin: 7px 0 0; padding-left: 22px; }
    footer { margin-top: 14px; padding: 11px 13px; border-left: 3px solid #80a58f; background: #f0f5ef; font-size: 8pt; }
    .caption { margin: 10px 0 0; font-size: 7pt; color: #6b7b73; text-align: right; }
    .preparation { display: flow-root; } .login-screen { float: right; width: 53mm; height: auto; margin: 0 0 12px 18px; border: 1px solid #d8e2db; border-radius: 8px; }
    .preparation ol { padding-left: 22px; } .preparation li + li { margin-top: 8px; }
    .faq-page .faq { margin-top: 12px; } .faq-page .qa { margin: 7px 0; padding: 8px 12px; font-size: 8pt; line-height: 1.7; } .faq-page h3 { font-size: 9pt; }
  </style></head><body>
    <article class="print-page"><p class="eyebrow">AudioInterview / はじめての方へ　1 / 6</p><h1>${escape(manualContent.title)}</h1>
    <p class="intro">${escape(manualContent.introduction)}</p>
    <section class="preparation"><h2>${escape(preparation.title)}</h2><p>${escape(preparation.browser)}</p>
    <img class="login-screen" src="data:image/png;base64,${login.toString('base64')}" alt="${escape(preparation.imageAlt)}">
    <ol>${preparation.instructions.map(instruction => `<li>${escape(instruction)}</li>`).join('')}</ol><p class="note">${escape(preparation.note)}</p></section>
    </article>
    ${patternPages.join('')}
    <article class="print-page faq-page"><p class="eyebrow">AudioInterview / 音声操作で困ったときに　5 / 6</p>
    <div class="repeat-box"><h2>${escape(repeat.title)}</h2><p>${escape(repeat.text)}</p><p class="repeat-cycle">${escape(repeat.callout)}</p></div>
    ${illustration}<p class="note">${escape(repeat.availability)}</p>
    <section class="faq"><h1>こんなときは？</h1>${questions.slice(0, 5).map(item => `<div class="qa"><h3>Q. ${escape(item.question)}</h3><p>${escape(item.answer)}</p>${item.instructions.length ? `<ol>${item.instructions.map(instruction => `<li>${escape(instruction)}</li>`).join('')}</ol>` : ''}${item.note ? `<p class="note">${escape(item.note)}</p>` : ''}</div>`).join('')}</section></article>
    <article class="print-page"><p class="eyebrow">AudioInterview　6 / 6</p>
    <section class="faq">${questions.slice(5).map(item => `<div class="qa"><h3>Q. ${escape(item.question)}</h3><p>${escape(item.answer)}</p><p class="note">${escape(item.note)}</p></div>`).join('')}</section>
    <footer>${escape(manualContent.help)}</footer></article>
  </body></html>`
}
