import { useEffect, useRef } from 'react'
import { manualContent } from './manualContent'
import './OperationManual.css'

export function OperationManual({ firstTime, saving, error, onClose }: {
  firstTime: boolean; saving: boolean; error: string; onClose: () => void
}) {
  const dialog = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    dialog.current?.focus()
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape' && !firstTime && !saving) {
        event.preventDefault()
        onClose()
      }
      if (event.key !== 'Tab') return
      const elements = dialog.current?.querySelectorAll<HTMLElement>('a[href], button:not(:disabled), [tabindex="0"]')
      if (!elements?.length) return
      const first = elements[0]
      const last = elements[elements.length - 1]
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) {
        event.preventDefault(); last.focus()
      } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog.current)) {
        event.preventDefault(); first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', onKey)
      // Prevent focusing the answer field from cancelling a paused recording.
      if (previous?.isConnected && !previous.matches('textarea, input')) previous.focus()
    }
  }, [firstTime, saving, onClose])

  return <div className="manual-backdrop">
    <div ref={dialog} className="manual-dialog" role="dialog" aria-modal="true" aria-labelledby="manual-title" aria-describedby="manual-introduction" tabIndex={-1}>
      <header className="manual-header">
        <div><p className="manual-eyebrow">{firstTime ? 'はじめての方へ' : 'いつでも確認できます'}</p><h1 id="manual-title">{manualContent.title}</h1></div>
        {!firstTime && <button className="manual-close" onClick={onClose} aria-label="操作マニュアルを閉じる">閉じる ×</button>}
      </header>
      <div className="manual-body">
        <p id="manual-introduction" className="manual-introduction">{manualContent.introduction}</p>
        <ul className="manual-highlights">{manualContent.highlights.map(item => <li key={item.title}>
          <strong>{item.title}</strong><span>{item.text}</span>
        </li>)}</ul>
        <ol className="manual-steps">{manualContent.steps.map((step, index) => <li key={step.title}>
          <h2><span>{index + 1}</span>{step.title}</h2>
          <p className="manual-step-key">{step.keyPoint}</p>
          <a href={step.image} target="_blank" rel="noreferrer" aria-label={`手順${index + 1}の画面を拡大する`}><img src={step.image} alt={step.alt} width="430" height="860" /></a>
          <p>{step.text}</p><p className="manual-note">{step.note}</p>
        </li>)}</ol>
        <section className="manual-repeat" aria-labelledby="manual-repeat-title">
          <h2 id="manual-repeat-title">{manualContent.repeat.title}</h2>
          {manualContent.repeat.image && <img className="manual-work-illustration" src={manualContent.repeat.image} alt={manualContent.repeat.imageAlt} />}
          <p>{manualContent.repeat.text}</p>
          <p className="manual-repeat-cycle">{manualContent.repeat.callout}</p>
          <p className="manual-note">{manualContent.repeat.availability}</p>
        </section>
        <section className="manual-questions" aria-labelledby="manual-questions-title">
          <h2 id="manual-questions-title">こんなときは？</h2>
          {manualContent.questions.map(item => <details key={item.question}>
            <summary>{item.question}</summary>
            <p>{item.answer}</p>
            {item.instructions.length > 0 && <ol>{item.instructions.map(instruction => <li key={instruction}>{instruction}</li>)}</ol>}
            {item.note && <p className="manual-note">{item.note}</p>}
          </details>)}
        </section>
        <p className="manual-help">{manualContent.help}</p>
      </div>
      <footer className="manual-footer">
        <a href="/manual/interview-manual.pdf" download>PDFを保存</a>
        {error && <p role="alert">{error}</p>}
        <button className="primary" onClick={onClose} disabled={saving}>{saving ? '確認を保存しています…' : firstTime ? '確認しました' : 'インタビューに戻る'}</button>
      </footer>
    </div>
  </div>
}
