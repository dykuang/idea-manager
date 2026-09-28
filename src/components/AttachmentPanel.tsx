import { useState } from 'react'
import { Copy, ExternalLink, File, FilePlus2, FolderOpen, Link2Off, LoaderCircle, TriangleAlert } from 'lucide-react'
import { api } from '../api'
import type { Attachment, Idea, Project } from '../types'

function sizeLabel(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function AttachmentPanel({ idea, project, onChanged }: {
  idea: Idea
  project?: Project
  onChanged: () => Promise<void>
}) {
  const files = (idea.attachments ?? []).filter(file => file.asset_role !== 'figure')
  const [path, setPath] = useState('')
  const [mode, setMode] = useState<'linked' | 'managed'>(project?.workspace_mode === 'managed' ? 'managed' : 'linked')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function browse() {
    setError('')
    try { setPath((await api.pickFile(project?.workspace_path ?? '')).path) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not open the file picker') }
  }

  async function attach() {
    if (!path.trim()) return
    setBusy(true); setError('')
    try { await api.attachFile(idea.id, path, mode); setPath(''); await onChanged() }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not attach that file') }
    finally { setBusy(false) }
  }

  async function act(action: 'open' | 'reveal', file: Attachment) {
    setError('')
    try { action === 'open' ? await api.openAttachment(file.id) : await api.revealAttachment(file.id) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not access that file') }
  }

  return <div className="attachment-panel">
    {files.map(file => <article className={`attachment-row ${file.exists ? '' : 'missing'}`} key={file.id}>
      <div className="attachment-icon">{file.exists ? <File size={17}/> : <TriangleAlert size={17}/>}</div>
      <div><strong>{file.display_name}</strong><span>{file.storage_mode === 'managed' ? 'Managed copy' : 'Linked original'} · {sizeLabel(file.size_bytes)}{!file.exists && ' · Missing'}</span><code title={file.absolute_path}>{file.absolute_path}</code></div>
      <aside><button title="Copy stable file reference" onClick={() => void navigator.clipboard.writeText(`[[file:${file.id}]]`)}><Copy size={13}/></button><button title="Open file" disabled={!file.exists} onClick={() => void act('open', file)}><ExternalLink size={13}/></button><button title="Show in folder" disabled={!file.exists} onClick={() => void act('reveal', file)}><FolderOpen size={13}/></button><button title="Remove from this idea (the file is not deleted)" onClick={async () => { await api.detachFile(idea.id, file.id); await onChanged() }}><Link2Off size={13}/></button></aside>
    </article>)}
    {!files.length && <p className="empty-small">No files attached. IdeaMiner stores file links in SQLite; your files remain on disk.</p>}
    <div className="attachment-add">
      <div><input value={path} onChange={event => setPath(event.target.value)} placeholder="Choose a local file or paste its full path"/><button className="button secondary small" onClick={browse}><FilePlus2 size={14}/> Choose</button></div>
      <div><select value={mode} onChange={event => setMode(event.target.value as 'linked' | 'managed')}><option value="linked">Link original file</option><option value="managed" disabled={project?.workspace_mode !== 'managed'}>Copy into managed workspace</option></select><button className="button primary small" disabled={busy || !path.trim()} onClick={attach}>{busy ? <LoaderCircle className="spin" size={14}/> : <FilePlus2 size={14}/>} Attach</button></div>
      {project?.workspace_mode !== 'managed' && <small>Managed copies require a project created with a managed workspace.</small>}
    </div>
    {error && <p className="workspace-error">{error}</p>}
  </div>
}
