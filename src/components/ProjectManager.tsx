import { useState } from 'react'
import { FolderPlus, FolderSearch, Layers3, X } from 'lucide-react'
import { api } from '../api'
import type { ProjectGroup } from '../types'
import { useI18n } from '../i18n'

export function ProjectManager({ groups, onClose, onCreateProject, onCreateGroup }: {
  groups: ProjectGroup[]
  onClose: () => void
  onCreateProject: (name: string, description: string, groupId: number | null, workspaceMode: 'library' | 'linked' | 'managed', workspacePath: string) => Promise<void>
  onCreateGroup: (name: string) => Promise<void>
}) {
  const { t } = useI18n()
  const [projectName, setProjectName] = useState('')
  const [description, setDescription] = useState('')
  const [groupId, setGroupId] = useState('')
  const [groupName, setGroupName] = useState('')
  const [saving, setSaving] = useState(false)
  const [workspaceMode, setWorkspaceMode] = useState<'library' | 'linked' | 'managed'>('library')
  const [workspacePath, setWorkspacePath] = useState('')
  const [error, setError] = useState('')

  async function browseFolder() {
    setError('')
    try { setWorkspacePath((await api.pickFolder(workspacePath)).path) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not open the folder picker') }
  }

  return <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && onClose()}>
    <div className="project-manager">
      <header><div><span className="eyebrow">{t('ORGANIZE THE GARDEN')}</span><h2>{t('Projects & groups')}</h2></div><button className="icon-button" aria-label={t('Close')} onClick={onClose}><X size={20}/></button></header>
      <form onSubmit={async e => { e.preventDefault(); setSaving(true); setError(''); try { await onCreateProject(projectName, description, groupId ? Number(groupId) : null, workspaceMode, workspacePath); setProjectName(''); setDescription(''); setWorkspacePath('') } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not create the project') } finally { setSaving(false) } }}>
        <h3><FolderPlus size={16}/> {t('New project')}</h3>
        <label>{t('Name')}<input required value={projectName} onChange={e => setProjectName(e.target.value)} placeholder={t('e.g. Robust graph learning')}/></label>
        <label>{t('Description')}<input value={description} onChange={e => setDescription(e.target.value)} placeholder={t('Optional purpose or scope')}/></label>
        <label>{t('Project group')}<select value={groupId} onChange={e => setGroupId(e.target.value)}><option value="">{t('No group')}</option>{groups.map(group => <option value={group.id} key={group.id}>{group.name}</option>)}</select></label>
        <label>{t('Local files')}<select value={workspaceMode} onChange={e => { setWorkspaceMode(e.target.value as 'library' | 'linked' | 'managed'); setWorkspacePath('') }}><option value="library">{t('Library only — no project folder')}</option><option value="linked">{t('Link an existing folder')}</option><option value="managed">{t('Create a managed project workspace')}</option></select></label>
        {workspaceMode !== 'library' && <div className="workspace-folder-field"><label>{t(workspaceMode === 'managed' ? 'Parent folder' : 'Existing folder')}<input required value={workspacePath} onChange={e => setWorkspacePath(e.target.value)} placeholder="C:\\Users\\you\\Research"/></label><button type="button" className="button secondary small" onClick={browseFolder}><FolderSearch size={14}/> {t('Browse')}</button></div>}
        {workspaceMode === 'managed' && <p className="workspace-help">IdeaMiner will create a new project-named folder here with a hidden <code>.ideaminer</code> area for managed copies and exports.</p>}
        {workspaceMode === 'linked' && <p className="workspace-help">The existing folder stays under your control. IdeaMiner stores only links and never deletes its files.</p>}
        {error && <p className="workspace-error">{error}</p>}
        <button className="button primary" disabled={saving || (workspaceMode !== 'library' && !workspacePath.trim())}>{t('Create project')}</button>
      </form>
      <form onSubmit={async e => { e.preventDefault(); setSaving(true); try { await onCreateGroup(groupName); setGroupName('') } finally { setSaving(false) } }}>
        <h3><Layers3 size={16}/> {t('New project group')}</h3>
        <label>{t('Name')}<input required value={groupName} onChange={e => setGroupName(e.target.value)} placeholder={t('e.g. Active research')}/></label>
        <button className="button secondary" disabled={saving}>{t('Create group')}</button>
      </form>
    </div>
  </div>
}
