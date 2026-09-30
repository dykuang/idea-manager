import { useEffect, useRef, useState } from 'react'
import { Columns2, FilePlus2, Link2, X } from 'lucide-react'
import { api } from '../api'
import type { Idea, Project, Status } from '../types'
import { IdeaMarkdown } from './IdeaMarkdown'
import { useI18n } from '../i18n'

interface Props {
  idea?: Idea | null
  onClose: () => void
  projects: Project[]
  defaultProjectId: number
  ideas: Idea[]
  onSave: (data: { title: string; content: string; raw_text: string; status: Status; tags: string[]; project_id: number }) => Promise<Idea>
}

export function IdeaEditor({ idea, projects, defaultProjectId, ideas, onClose, onSave }: Props) {
  const { t } = useI18n()
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [status, setStatus] = useState<Status>('seed')
  const [tags, setTags] = useState('')
  const [saving, setSaving] = useState(false)
  const [projectId, setProjectId] = useState(defaultProjectId)
  const [queuedFiles, setQueuedFiles] = useState<string[]>([])
  const [fileError, setFileError] = useState('')
  const sourceRef = useRef<HTMLTextAreaElement>(null)
  const previewRef = useRef<HTMLDivElement>(null)
  const scrollOwner = useRef<'writing' | 'preview' | null>(null)
  const scrollRelease = useRef<number | null>(null)

  useEffect(() => {
    setTitle(idea?.title ?? '')
    setContent(idea?.content ?? '')
    setStatus(idea?.status ?? 'seed')
    setTags(idea?.tags.join(', ') ?? '')
    setProjectId(idea?.project_id ?? defaultProjectId)
    setQueuedFiles([]); setFileError('')
  }, [idea, defaultProjectId])

  async function chooseQuickFile() {
    setFileError('')
    try {
      const project = projects.find(item => item.id === projectId)
      const path = (await api.pickFile(project?.workspace_path ?? '')).path
      if (path && !queuedFiles.includes(path)) setQueuedFiles(current => [...current, path])
    } catch (reason) { setFileError(reason instanceof Error ? reason.message : 'Could not open the file picker') }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setSaving(true)
    try {
      const cleanTags = tags.split(',').map(t => t.trim()).filter(Boolean)
      const saved = await onSave({ title, content, raw_text: `${title}\n\n${content}`.trim(), status, tags: cleanTags, project_id: projectId })
      if (queuedFiles.length) {
        const linked = await Promise.all(queuedFiles.map(path => api.attachFile(saved.id, path, 'linked')))
        const references = linked.filter(file => !content.includes(`[[file:${file.id}`)).map(file => `- [[file:${file.id}|${file.absolute_path}]]`)
        if (references.length) {
          const nextContent = `${content.trim()}${content.trim() ? '\n\n' : ''}## Local files\n${references.join('\n')}`
          await api.updateIdea(saved.id, { title, content: nextContent, status, tags: cleanTags, expected_updated_at: saved.updated_at })
        }
      }
      onClose()
    } catch (reason) { setFileError(reason instanceof Error ? reason.message : 'Could not link the selected file') }
    finally { setSaving(false) }
  }

  function synchronize(source: HTMLElement, target: HTMLElement, owner: 'writing' | 'preview') {
    if (scrollOwner.current && scrollOwner.current !== owner) return
    scrollOwner.current = owner
    const sourceRange = source.scrollHeight - source.clientHeight
    const targetRange = target.scrollHeight - target.clientHeight
    target.scrollTop = sourceRange > 0 ? (source.scrollTop / sourceRange) * Math.max(0, targetRange) : 0
    if (scrollRelease.current !== null) window.clearTimeout(scrollRelease.current)
    scrollRelease.current = window.setTimeout(() => { scrollOwner.current = null }, 80)
  }

  return <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && onClose()}>
    <form className="editor" onSubmit={submit}>
      <header><div><span className="eyebrow">{t(idea ? 'REFINE THE THOUGHT' : 'CAPTURE A SPARK')}</span><h2>{t(idea ? 'Edit idea' : 'New idea')}</h2></div><button type="button" className="icon-button" aria-label={t('Close')} onClick={onClose}><X size={20}/></button></header>
      <label>{t('Title')}<input autoFocus required maxLength={240} value={title} onChange={e => setTitle(e.target.value)} placeholder={t('A concise name for the idea')} /></label>
      <div className="editor-notes-heading"><strong>{t('Notes')}</strong><span><Columns2 size={13}/> {t('Synchronized Markdown + LaTeX preview')}</span></div>
      <div className="editor-compose">
        <section className="compose-pane"><label htmlFor="idea-notes">{t('Writing')}</label><textarea id="idea-notes" ref={sourceRef} value={content} onChange={e => setContent(e.target.value)} onScroll={event => previewRef.current && synchronize(event.currentTarget, previewRef.current, 'writing')} placeholder={t('Describe the idea… Use $x^2$ inline or $$\\mathcal{L} = \\sum_i \\ell_i$$ for a display equation.')}/></section>
        <section className="compose-pane preview-pane" aria-label={t('Rendered preview')}><div className="compose-pane-label">{t('Preview')}</div><div ref={previewRef} className="markdown" onScroll={event => sourceRef.current && synchronize(event.currentTarget, sourceRef.current, 'preview')}>{content.trim() ? <IdeaMarkdown content={content} ideas={ideas} attachments={idea?.attachments}/> : <p className="preview-placeholder">{t('The rendered note will appear here beside your source.')}</p>}</div></section>
      </div>
      <div className="form-row">
        <label>{t('Status')}<select value={status} onChange={e => setStatus(e.target.value as Status)}><option value="seed">{t('Seed')}</option><option value="exploring">{t('Exploring')}</option><option value="promising">{t('Promising')}</option><option value="parked">{t('Parked')}</option></select></label>
        <label>{t('Tags')}<input value={tags} onChange={e => setTags(e.target.value)} placeholder={t('ml, methods, reading')} /></label>
      </div>
      {!idea && <label>{t('Project')}<select value={projectId} onChange={e => setProjectId(Number(e.target.value))}>{projects.filter(project => project.system_key !== 'recycle').map(project => <option value={project.id} key={project.id}>{project.name}{project.group_name ? ` — ${project.group_name}` : ''}</option>)}</select></label>}
      <section className="editor-file-links"><div><strong><Link2 size={14}/> {t('Local file links')}</strong><span>{t('Paths and metadata only—file contents are never stored in your idea.')}</span></div><button type="button" className="button secondary small" onClick={() => void chooseQuickFile()}><FilePlus2 size={14}/> {t('Link a file')}</button>{queuedFiles.length > 0 && <ul>{queuedFiles.map(path => <li key={path}><code title={path}>{path}</code><button type="button" aria-label={t('Remove file link')} onClick={() => setQueuedFiles(current => current.filter(item => item !== path))}><X size={13}/></button></li>)}</ul>}<small>{t('Saving adds a clickable `[[file:…]]` reference to the note. The Agent can locate it by path and only reads it if you explicitly select it for a run.')}</small></section>
      {!idea && <p className="raw-note">{t('The first capture is preserved verbatim, even as the idea evolves.')}</p>}
      {fileError && <p className="workspace-error">{fileError}</p>}
      <footer><button type="button" className="button secondary" onClick={onClose}>{t('Cancel')}</button><button className="button primary" disabled={saving}>{saving ? t('Saving…') : idea ? t('Save changes') : t('Plant idea')}</button></footer>
    </form>
  </div>
}
