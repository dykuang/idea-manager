import { useState } from 'react'
import { AlertTriangle, FileJson, X } from 'lucide-react'
import type { ImportPreview, ImportResult } from '../api'

export function ImportDialog({ filename, preview, onClose, onImport }: {
  filename: string
  preview: ImportPreview
  onClose: () => void
  onImport: (duplicateStrategy: 'skip' | 'copy' | 'update', projectStrategy: 'merge' | 'rename') => Promise<ImportResult>
}) {
  const [duplicates, setDuplicates] = useState<'skip' | 'copy' | 'update'>('skip')
  const [projects, setProjects] = useState<'merge' | 'rename'>('merge')
  const [importing, setImporting] = useState(false)
  const [result, setResult] = useState<ImportResult | null>(null)

  return <div className="modal-backdrop" onMouseDown={event => event.target === event.currentTarget && !importing && onClose()}>
    <div className="import-dialog">
      <header><div><span className="eyebrow">PORTABLE IDEA LIBRARY</span><h2>{result ? 'Import complete' : 'Review import'}</h2></div><button className="icon-button" onClick={onClose}><X size={20}/></button></header>
      {result ? <div className="import-result">
        <div className="import-success"><FileJson size={26}/></div>
        <p><strong>{result.ideas_created}</strong> topics created · <strong>{result.ideas_updated}</strong> updated · <strong>{result.ideas_skipped}</strong> skipped</p>
        <p>{result.projects_created} projects, {result.groups_created} groups, {result.relations_created} relations, and {result.experiments_created} experiments added.</p>
        <button className="button primary" onClick={onClose}>View imported ideas</button>
      </div> : <>
        <div className="import-file"><FileJson size={22}/><div><strong>{filename}</strong><span>IdeaMiner export version {preview.version}</span></div></div>
        <div className="import-counts"><div><strong>{preview.counts.ideas}</strong><span>Topics</span></div><div><strong>{preview.counts.projects}</strong><span>Projects</span></div><div><strong>{preview.counts.groups}</strong><span>Groups</span></div><div><strong>{preview.counts.relations}</strong><span>Relations</span></div><div><strong>{preview.counts.experiments ?? 0}</strong><span>Experiments</span></div></div>
        {(preview.duplicate_topics > 0 || preview.project_conflicts.length > 0 || preview.group_conflicts.length > 0) && <div className="import-warning"><AlertTriangle size={17}/><span>{preview.duplicate_topics} duplicate topics, {preview.project_conflicts.length} matching projects, and {preview.group_conflicts.length} matching groups found.</span></div>}
        <label>When a topic already exists<select value={duplicates} onChange={event => setDuplicates(event.target.value as typeof duplicates)}><option value="skip">Skip the duplicate (recommended)</option><option value="copy">Create another copy</option><option value="update">Update the existing topic</option></select></label>
        <label>When a project or group name matches<select value={projects} onChange={event => setProjects(event.target.value as typeof projects)}><option value="merge">Merge into the existing project (recommended)</option><option value="rename">Create a separate “imported” project</option></select></label>
        <p className="transaction-note">The import runs as one SQLite transaction. If any item fails validation, nothing is changed.</p>
        <footer><button className="button secondary" onClick={onClose}>Cancel</button><button className="button primary" disabled={importing} onClick={async () => { setImporting(true); try { setResult(await onImport(duplicates, projects)) } finally { setImporting(false) } }}>{importing ? 'Importing…' : `Import ${preview.counts.ideas} topics`}</button></footer>
      </>}
    </div>
  </div>
}
