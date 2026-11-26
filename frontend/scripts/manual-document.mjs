import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { manualContent } from '../src/manualContent.ts'

const escape = value => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;')

export async function manualDocument(directory) {
  const cards = await Promise.all(manualContent.steps.map(async (step, index) => {
    const png = await readFile(path.join(directory, path.basename(step.image)))
    return `<section class="screen-card"><h2><b>${index + 1}</b>${escape(step.title)}</h2><p class="key-point">${escape(step.keyPoint)}</p><img src="data:image/png;base64,${png.toString('base64')}" alt="${escape(step.alt)}"><p>${escape(step.text)}</p><p class="note">${escape(step.note)}</p></section>`
  }))
  const { repeat, questions } = manualContent
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
    .intro { margin: 0 0 13px; } .highlights { display: grid; grid-template-columns: repeat(3, 1fr); gap: 9px; margin-bottom: 16px; }
    .highlights div { padding: 9px; border: 1px solid #cbded2; border-radius: 7px; background: #edf5ef; font-size: 8pt; } .highlights strong { display: block; color: #245d4e; font-size: 9pt; }
    .steps { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    .screen-card { break-inside: avoid; padding: 12px; border: 1px solid #d8e2db; border-radius: 10px; } .screen-card h2 { display: flex; align-items: center; gap: 7px; font-size: 10.5pt; line-height: 1.6; }
    .screen-card h2 b { display: inline-grid; flex-shrink: 0; place-items: center; width: 23px; height: 23px; border-radius: 50%; color: white; background: #3d7d70; font-size: 10pt; }
    .key-point { margin: 0 0 10px; padding: 6px 8px; border-radius: 5px; color: #245d4e; background: #edf5ef; font-weight: 700; font-size: 8.5pt; }
    .screen-card img { display: block; width: 60mm; max-width: 100%; height: auto; margin: 0 auto; border: 1px solid #e2e2d8; border-radius: 6px; }
    p { margin: 9px 0 0; } .note { color: #526a5f; font-size: 8pt; }
    .repeat-box { margin-top: 16px; padding: 14px; border: 1px solid #cbded2; border-radius: 9px; background: #f0f6ef; }
    .repeat-cycle { padding: 10px; border-radius: 7px; color: #245d4e; background: white; font-weight: 700; }
    .repeat-text { font-size: 10pt; }
    .work-illustration { display: block; width: 100%; max-height: 155px; margin: 12px auto; object-fit: contain; }
    .faq { margin-top: 20px; } .qa { break-inside: avoid; margin: 9px 0; padding: 11px 14px; border: 1px solid #d8e2db; border-radius: 8px; }
    h3 { margin: 0; color: #315d50; font-size: 10pt; } .qa p { margin-top: 6px; } .qa ol { margin: 7px 0 0; padding-left: 22px; }
    footer { margin-top: 14px; padding: 11px 13px; border-left: 3px solid #80a58f; background: #f0f5ef; font-size: 8pt; }
    .caption { margin: 10px 0 0; font-size: 7pt; color: #6b7b73; text-align: right; }
  </style></head><body>
    <article class="print-page"><p class="eyebrow">AudioInterview / はじめての方へ　1 / 3</p><h1>${escape(manualContent.title)}</h1>
    <p class="intro">${escape(manualContent.introduction)}</p>
    <div class="highlights">${manualContent.highlights.map(item => `<div><strong>${escape(item.title)}</strong>${escape(item.text)}</div>`).join('')}</div>
    <main class="steps">${cards.slice(0, 2).join('')}</main><p class="caption">画面は操作説明用のサンプルです。上部の状態表示から下部の操作欄までを掲載しています。</p></article>
    <article class="print-page"><p class="eyebrow">AudioInterview / 文字入力・終了と次の回　2 / 3</p><h1>文字でも答えられます。終わっても、そのままで。</h1>
    <main class="steps">${cards.slice(2).join('')}</main><div class="repeat-box"><h2>${escape(repeat.title)}</h2><p>${escape(repeat.text)}</p><p class="repeat-cycle">${escape(repeat.callout)}</p></div></article>
    <article class="print-page"><p class="eyebrow">AudioInterview / 1日に何度でも・困ったときに　3 / 3</p><h1>${escape(repeat.title)}</h1>
    ${illustration}<p class="repeat-text">${escape(repeat.text)}</p><div class="repeat-box"><p class="repeat-cycle">${escape(repeat.callout)}</p><p class="note">${escape(repeat.availability)}</p></div>
    <section class="faq"><h2>こんなときは？</h2>${questions.map(item => `<div class="qa"><h3>Q. ${escape(item.question)}</h3><p>${escape(item.answer)}</p>${item.instructions.length ? `<ol>${item.instructions.map(instruction => `<li>${escape(instruction)}</li>`).join('')}</ol>` : ''}${item.note ? `<p class="note">${escape(item.note)}</p>` : ''}</div>`).join('')}</section>
    <footer>${escape(manualContent.help)}</footer></article>
  </body></html>`
}
