import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, Copy, Crown, ExternalLink, FileImage, FolderOpen, ImagePlus, Link2Off, LoaderCircle, X } from 'lucide-react'
import { api } from '../api'
import type { Attachment, Idea } from '../types'

const isEditable = (target: EventTarget | null) => target instanceof HTMLElement &&
  (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))

export function FigureGallery({ idea, onChanged }: { idea: Idea; onChanged: () => Promise<void> }) {
  const figures = useMemo(() => (idea.attachments ?? []).filter(file => file.asset_role === 'figure').sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0)), [idea.attachments])
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [lightbox, setLightbox] = useState<number | null>(null)

  async function upload(files: FileList | File[]) {
    const images = Array.from(files)
    if (!images.length) return
    setBusy(true); setError('')
    try {
      for (const file of images) await api.uploadFigure(idea.id, file)
      await onChanged()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not add that image')
    } finally { setBusy(false); if (input.current) input.current.value = '' }
  }

  useEffect(() => {
    const paste = (event: ClipboardEvent) => {
      if (isEditable(event.target)) return
      const item = Array.from(event.clipboardData?.items ?? []).find(entry => entry.type.startsWith('image/'))
      const blob = item?.getAsFile()
      if (!blob) return
      event.preventDefault()
      const extension = blob.type === 'image/jpeg' ? 'jpg' : blob.type.split('/')[1] || 'png'
      void upload([new File([blob], `pasted-figure.${extension}`, { type: blob.type })])
    }
    const avoidNavigation = (event: DragEvent) => {
      if (event.dataTransfer?.types.includes('Files')) event.preventDefault()
    }
    window.addEventListener('paste', paste)
    window.addEventListener('dragover', avoidNavigation)
    window.addEventListener('drop', avoidNavigation)
    return () => {
      window.removeEventListener('paste', paste)
      window.removeEventListener('dragover', avoidNavigation)
      window.removeEventListener('drop', avoidNavigation)
    }
  }, [idea.id])

  useEffect(() => {
    if (lightbox === null) return
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); setLightbox(null) }
      if (event.key === 'ArrowRight') setLightbox(index => index === null ? null : (index + 1) % figures.length)
      if (event.key === 'ArrowLeft') setLightbox(index => index === null ? null : (index - 1 + figures.length) % figures.length)
    }
    window.addEventListener('keydown', key, true)
    return () => window.removeEventListener('keydown', key, true)
  }, [lightbox, figures.length])

  async function update(file: Attachment, data: Partial<Pick<Attachment, 'asset_role' | 'caption' | 'sort_order' | 'is_cover'>>) {
    setError('')
    try { await api.updateIdeaAttachment(idea.id, file.id, data); await onChanged() }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not update this figure') }
  }

  async function reorder(index: number, direction: -1 | 1) {
    const next = index + direction
    if (next < 0 || next >= figures.length) return
    const order = [...figures]
    ;[order[index], order[next]] = [order[next], order[index]]
    await Promise.all(order.map((file, position) => api.updateIdeaAttachment(idea.id, file.id, { sort_order: position })))
    await onChanged()
  }

  async function fileAction(file: Attachment, action: 'open' | 'reveal') {
    try { action === 'open' ? await api.openAttachment(file.id) : await api.revealAttachment(file.id) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not access this figure') }
  }

  const current = lightbox === null ? null : figures[lightbox]
  return <section className="figure-gallery" onDragOver={event => event.preventDefault()} onDrop={event => {
    const files = Array.from(event.dataTransfer.files)
    if (files.length) { event.preventDefault(); void upload(files) }
  }}>
    <header><h3><FileImage size={15}/> Figures <span>{figures.length}</span></h3><button className="button secondary small" onClick={() => input.current?.click()} disabled={busy}>{busy ? <LoaderCircle className="spin" size={14}/> : <ImagePlus size={14}/>} Add figures</button>
      <input ref={input} className="hidden-file-input" type="file" accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml,.png,.jpg,.jpeg,.webp,.gif,.svg" multiple onChange={event => { if (event.target.files) void upload(event.target.files) }}/>
    </header>
    {figures.length ? <div className="figure-grid">{figures.map((file, index) => <article className="figure-tile" key={file.id}>
      <button className="figure-preview" onClick={() => setLightbox(index)} aria-label={`View ${file.caption || file.display_name}`} disabled={!file.exists}>
        {file.exists ? <img loading="lazy" src={file.preview_url ?? `/api/attachments/${file.id}/content`} alt={file.caption || file.display_name}/> : <span className="figure-missing">Image file missing</span>}
        {file.is_cover && <span className="figure-cover"><Crown size={12}/> Cover</span>}
      </button>
      <input className="figure-caption" aria-label={`Caption for ${file.display_name}`} defaultValue={file.caption ?? ''} placeholder={file.display_name} onBlur={event => { if (event.target.value !== (file.caption ?? '')) void update(file, { caption: event.target.value }) }} onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur() }}/>
      <div className="figure-controls">
        <button title={file.is_cover ? 'Remove cover' : 'Set as cover'} aria-label={file.is_cover ? 'Remove cover' : 'Set as cover'} onClick={() => void update(file, { is_cover: !file.is_cover })}><Crown size={13}/></button>
        <button title="Move left" aria-label="Move figure left" disabled={index === 0} onClick={() => void reorder(index, -1)}><ArrowLeft size={13}/></button>
        <button title="Move right" aria-label="Move figure right" disabled={index === figures.length - 1} onClick={() => void reorder(index, 1)}><ArrowRight size={13}/></button>
        <button title="Open file" aria-label="Open figure file" disabled={!file.exists} onClick={() => void fileAction(file, 'open')}><ExternalLink size={13}/></button>
        <button title="Show in folder" aria-label="Show figure in folder" disabled={!file.exists} onClick={() => void fileAction(file, 'reveal')}><FolderOpen size={13}/></button>
        <button title="Copy stable file reference" aria-label="Copy stable file reference" onClick={() => void navigator.clipboard.writeText(`[[file:${file.id}]]`)}><Copy size={13}/></button>
        <button title="Treat as normal attachment" aria-label="Treat as normal attachment" onClick={() => void update(file, { asset_role: 'attachment' })}><Link2Off size={13}/></button>
        <button title="Detach from this idea" aria-label="Detach figure from idea" onClick={async () => { await api.detachFile(idea.id, file.id); await onChanged() }}><X size={13}/></button>
      </div>
    </article>)}</div> : <button className="figure-drop-empty" onClick={() => input.current?.click()} onDragOver={event => event.preventDefault()}>
      <ImagePlus size={16}/><span>Drop images here or add a figure. Paste a copied image with Ctrl+V.</span>
    </button>}
    {error && <p className="figure-error" role="alert">{error}</p>}
    {current && <div className="figure-lightbox" role="dialog" aria-modal="true" aria-label={`Figure: ${current.caption || current.display_name}`} onMouseDown={event => { if (event.target === event.currentTarget) setLightbox(null) }}>
      <div className="figure-lightbox-panel"><header><div><strong>{current.caption || current.display_name}</strong><span>{current.display_name}</span></div><button aria-label="Close figure" onClick={() => setLightbox(null)}><X size={20}/></button></header>
        <div className="figure-lightbox-image">{current.exists && <img src={current.preview_url ?? `/api/attachments/${current.id}/content`} alt={current.caption || current.display_name}/>}</div>
        {figures.length > 1 && <><button className="figure-lightbox-prev" aria-label="Previous figure" onClick={() => setLightbox((lightbox! - 1 + figures.length) % figures.length)}><ArrowLeft/></button><button className="figure-lightbox-next" aria-label="Next figure" onClick={() => setLightbox((lightbox! + 1) % figures.length)}><ArrowRight/></button></>}
        <footer><button className="button secondary small" onClick={() => void fileAction(current, 'open')}><ExternalLink size={13}/> Open file</button><button className="button secondary small" onClick={() => void fileAction(current, 'reveal')}><FolderOpen size={13}/> Show in folder</button></footer>
      </div>
    </div>}
  </section>
}
