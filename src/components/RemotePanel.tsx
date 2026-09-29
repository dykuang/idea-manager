import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { ArrowDownToLine, ArrowUpFromLine, Check, CircleAlert, CircleCheck, Clock3, Cloud, File, FolderOpen, LoaderCircle, Pencil, Plus, RefreshCw, Server, ShieldAlert, Trash2, X } from 'lucide-react'
import { api } from '../api'
import type { Project, ProjectSyncPreview, RemoteMachine, RemoteStatus } from '../types'
import './RemotePanel.css'

type Draft = { name: string; host: string; username: string; port: string; root_path: string }
const blank: Draft = { name: '', host: '', username: '', port: '', root_path: '~/IdeaMinerProjects' }
const formatSize = (value: number | null) => value === null ? '—' : value < 1024 ? `${value} B` : value < 1024 * 1024 ? `${(value / 1024).toFixed(1)} KB` : `${(value / 1024 / 1024).toFixed(1)} MB`

export function RemotePanel({ projects, onClose }: { projects: Project[]; onClose: () => void }) {
  const [machines, setMachines] = useState<RemoteMachine[]>([])
  const [statuses, setStatuses] = useState<Record<number, RemoteStatus>>({})
  const [machineId, setMachineId] = useState<number | null>(null)
  const [draft, setDraft] = useState<Draft>(blank)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [projectId, setProjectId] = useState<number | null>(projects.find(item => item.system_key === null)?.id ?? null)
  const [direction, setDirection] = useState<'push' | 'pull'>('push')
  const [localRoot, setLocalRoot] = useState('')
  const [preview, setPreview] = useState<ProjectSyncPreview | null>(null)
  const [selectedPaths, setSelectedPaths] = useState<string[]>([])
  const [deletePaths, setDeletePaths] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [summary, setSummary] = useState('')

  const selectedProject = useMemo(() => projects.find(item => item.id === projectId) ?? null, [projects, projectId])

  const refresh = useCallback(async () => {
    try {
      const list = await api.remoteMachines()
      setMachines(list)
      setMachineId(current => current === null && list.length ? list[0].id : current)
      const results = await Promise.all(list.map(async item => [item.id, await api.checkRemoteMachine(item.id).catch(reason => ({ status: 'offline' as const, root_exists: false, message: reason instanceof Error ? reason.message : 'Connection check failed' }))] as const))
      setStatuses(Object.fromEntries(results))
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not load remote machines') }
  }, [])

  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 30000); return () => window.clearInterval(timer) }, [refresh])

  async function browseLocal() {
    try { setLocalRoot((await api.pickFolder(localRoot || selectedProject?.workspace_path || '')).path) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not open the folder picker') }
  }

  async function checkMachine(id: number) {
    const status = await api.checkRemoteMachine(id).catch(reason => ({ status: 'offline' as const, root_exists: false, message: reason instanceof Error ? reason.message : 'Connection check failed' }))
    setStatuses(current => ({ ...current, [id]: status }))
  }

  function editMachine(machine?: RemoteMachine) {
    setEditingId(machine?.id ?? null)
    setDraft(machine ? { name: machine.name, host: machine.host, username: machine.username, port: machine.port ? String(machine.port) : '', root_path: machine.root_path } : blank)
    setShowForm(true); setError('')
  }

  async function saveMachine(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    const data = { name: draft.name.trim(), host: draft.host.trim(), username: draft.username.trim(), port: Number(draft.port || 0), root_path: draft.root_path.trim() }
    try {
      const saved = editingId ? await api.updateRemoteMachine(editingId, data) : await api.createRemoteMachine(data)
      setMachineId(saved.id); setShowForm(false); setEditingId(null); setDraft(blank); await refresh(); setMachineId(saved.id)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not save this remote machine') }
    finally { setBusy(false) }
  }

  async function removeMachine(machine: RemoteMachine) {
    if (!window.confirm(`Remove the connection to ${machine.name}? No files on either machine will be deleted.`)) return
    try { await api.deleteRemoteMachine(machine.id); if (machineId === machine.id) setMachineId(null); setStatuses(current => { const next = { ...current }; delete next[machine.id]; return next }); await refresh() }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not remove this remote machine') }
  }

  async function makePreview() {
    if (!machineId || !projectId) return
    setBusy(true); setError(''); setSummary(''); setPreview(null)
    try {
      const result = await api.previewProjectSync({ machine_id: machineId, project_id: projectId, direction, local_root: localRoot || selectedProject?.workspace_path || '' })
      setPreview(result)
      setSelectedPaths(result.items.filter(item => item.status === 'new').map(item => item.path))
      setDeletePaths([])
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not preview this sync') }
    finally { setBusy(false) }
  }

  async function runSync() {
    if (!preview) return
    setBusy(true); setError('')
    try {
      const result = await api.executeProjectSync({ preview_id: preview.preview_id, selected_paths: selectedPaths, delete_paths: deletePaths })
      setSummary(`${result.transferred} file${result.transferred === 1 ? '' : 's'} transferred · ${result.skipped} skipped · ${result.deleted} deleted`)
      setPreview(null); setDeletePaths([]); await refresh()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'The sync did not finish') }
    finally { setBusy(false) }
  }

  const statusFor = (machine: RemoteMachine) => statuses[machine.id]
  const selectedMachine = machines.find(item => item.id === machineId)
  const selectedStatus = selectedMachine ? statusFor(selectedMachine) : undefined
  const canSync = Boolean(machineId && projectId && selectedStatus?.status === 'connected')

  return <div className="modal-backdrop remote-backdrop" onMouseDown={event => event.target === event.currentTarget && !busy && onClose()}>
    <section className="remote-panel">
      <header><div><span className="eyebrow">SSH · SFTP</span><h2><Server size={24}/> Remote sync</h2><p>Move project files between this machine and your Ubuntu computer.</p></div><button className="icon-button" aria-label="Close remote panel" onClick={onClose}><X size={20}/></button></header>
      <div className="remote-columns">
        <aside className="remote-machines">
          <div className="remote-section-heading"><strong>Machines</strong><button className="button secondary small" onClick={() => editMachine()}><Plus size={14}/> Add</button></div>
          {!machines.length && <p className="remote-empty">Add an Ubuntu machine using its SSH host name or SSH config alias.</p>}
          {machines.map(machine => {
            const status = statusFor(machine)
            return <article key={machine.id} className={`remote-machine ${machineId === machine.id ? 'active' : ''}`}>
              <button className="remote-machine-select" onClick={() => { setMachineId(machine.id); setPreview(null); setError('') }}><span className={`remote-status-dot ${status?.status ?? 'checking'}`}/><span><strong>{machine.name}</strong><small>{machine.username ? `${machine.username}@` : ''}{machine.host}{machine.port ? `:${machine.port}` : ''}</small></span></button>
              <div className="remote-machine-actions"><button title="Check SSH connection" onClick={() => void checkMachine(machine.id)}><RefreshCw size={13}/></button><button title="Edit machine" onClick={() => editMachine(machine)}><Pencil size={13}/></button><button title="Remove machine" onClick={() => void removeMachine(machine)}><Trash2 size={13}/></button></div>
              {status && <small className={`remote-status-text ${status.status}`}>{status.status === 'connected' ? 'Connected' : status.status === 'host_key_attention' ? 'Host key attention' : 'Offline'}</small>}
            </article>
          })}
          {showForm && <form className="remote-machine-form" onSubmit={event => void saveMachine(event)}>
            <h3>{editingId ? 'Edit machine' : 'Add machine'}</h3>
            <label>Display name<input required maxLength={80} value={draft.name} onChange={event => setDraft(current => ({ ...current, name: event.target.value }))} placeholder="Ubuntu research server"/></label>
            <label>SSH host or alias<input required value={draft.host} onChange={event => setDraft(current => ({ ...current, host: event.target.value }))} placeholder="research-server"/></label>
            <div className="remote-form-row"><label>Username<input value={draft.username} onChange={event => setDraft(current => ({ ...current, username: event.target.value }))} placeholder="Use SSH config"/></label><label>Port<input type="number" min="0" max="65535" value={draft.port} onChange={event => setDraft(current => ({ ...current, port: event.target.value }))} placeholder="Config / 22"/></label></div>
            <label>Remote root folder<input required value={draft.root_path} onChange={event => setDraft(current => ({ ...current, root_path: event.target.value }))} placeholder="~/IdeaMinerProjects"/></label>
            <small>Authentication uses your SSH agent, SSH keys, and known_hosts. IdeaMiner does not save private keys or passphrases.</small>
            <div><button type="button" className="button secondary small" onClick={() => { setShowForm(false); setEditingId(null) }}>Cancel</button><button className="button primary small" disabled={busy}>{busy ? <LoaderCircle className="spin" size={14}/> : <Check size={14}/>} Save</button></div>
          </form>}
        </aside>

        <div className="remote-sync-area">
          {!machineId ? <div className="remote-empty large"><Cloud size={27}/><strong>Connect a machine to start</strong><span>SSH must be reachable and trusted in your local known_hosts file.</span></div> : <>
            <div className="remote-selected-machine"><div><span className="eyebrow">SELECTED MACHINE</span><strong>{selectedMachine?.name ?? 'Remote'}</strong><small>{selectedStatus?.message ?? 'Checking SSH connection…'}</small></div><span className={`remote-status-badge ${selectedStatus?.status ?? 'checking'}`}>{selectedStatus?.status === 'connected' ? <><CircleCheck size={14}/> Connected</> : selectedStatus?.status === 'host_key_attention' ? <><ShieldAlert size={14}/> Host key</> : <><CircleAlert size={14}/> Offline</>}</span></div>
            {selectedStatus?.status === 'host_key_attention' && <p className="remote-warning">Verify this server’s fingerprint using a trusted channel, then add it to your SSH <code>known_hosts</code> file and check again. Unknown or changed keys are never accepted automatically.</p>}
            <div className="remote-sync-form">
              <label>Project<select value={projectId ?? ''} onChange={event => { const id = Number(event.target.value) || null; setProjectId(id); const project = projects.find(item => item.id === id); setLocalRoot(project?.workspace_path ?? ''); setPreview(null) }}><option value="">Choose a project</option>{projects.filter(item => item.system_key === null).map(project => <option value={project.id} key={project.id}>{project.name}</option>)}</select></label>
              <fieldset><legend>Direction</legend><label><input type="radio" name="sync-direction" checked={direction === 'push'} onChange={() => { setDirection('push'); setPreview(null) }}/><ArrowUpFromLine size={15}/> Push to remote</label><label><input type="radio" name="sync-direction" checked={direction === 'pull'} onChange={() => { setDirection('pull'); setPreview(null) }}/><ArrowDownToLine size={15}/> Pull to this machine</label></fieldset>
              <label>Local project folder <span>{selectedProject?.workspace_path ? 'Project workspace' : 'Choose a folder if this project has no workspace'}</span><div className="remote-local-folder"><input value={localRoot} onChange={event => { setLocalRoot(event.target.value); setPreview(null) }} placeholder={selectedProject?.workspace_mode === 'library' ? 'Not set — attachments only for push' : 'Choose the project folder'}/><button type="button" className="button secondary small" onClick={() => void browseLocal()}><FolderOpen size={14}/> Browse</button></div></label>
              <div className="remote-sync-actions"><button className="button primary" disabled={!canSync || !projectId || busy} onClick={() => void makePreview()}>{busy ? <LoaderCircle className="spin" size={15}/> : <Clock3 size={15}/>} Preview {direction}</button><small>Compare file contents before transferring. SQLite and idea records stay local.</small></div>
            </div>
          </>}
          {summary && <p className="remote-success"><Check size={15}/>{summary}</p>}
          {preview && <section className="sync-preview"><header><div><strong>Sync preview</strong><span>{preview.direction === 'push' ? 'This machine → Ubuntu' : 'Ubuntu → this machine'} · {preview.remote_path}</span></div><button className="button secondary small" onClick={() => setPreview(null)}>Change</button></header>
            <div className="sync-preview-items">{preview.items.map(item => {
              const included = selectedPaths.includes(item.path)
              const deleting = deletePaths.includes(item.path)
              return <label key={item.path} className={`sync-preview-row ${item.status}`}>
                <input type="checkbox" disabled={item.status === 'same'} checked={item.status === 'destination_only' ? deleting : included} onChange={event => item.status === 'destination_only' ? setDeletePaths(current => event.target.checked ? [...current, item.path] : current.filter(path => path !== item.path)) : setSelectedPaths(current => event.target.checked ? [...current, item.path] : current.filter(path => path !== item.path))}/>
                <File size={15}/><span className="sync-preview-path"><strong>{item.path}</strong><small>{item.status === 'new' ? 'New file' : item.status === 'same' ? 'Identical · skip' : item.status === 'conflict' ? 'Different contents · overwrite only if selected' : 'Only at destination · delete only if selected'}</small></span>
                <span className="sync-preview-size">{formatSize(item.source_size)}{item.destination_size !== null && item.status === 'conflict' ? ` / ${formatSize(item.destination_size)}` : ''}</span>
              </label>
            })}{preview.items.length === 0 && <p className="remote-empty">Both folders are empty or already in sync.</p>}</div>
            <footer><span>{selectedPaths.length} files selected · {deletePaths.length} deletions selected</span><button className="button primary" disabled={busy || (!selectedPaths.length && !deletePaths.length)} onClick={() => void runSync()}>{busy ? <LoaderCircle className="spin" size={15}/> : <Check size={15}/>} Sync selected</button></footer>
          </section>}
          {error && <div className="error-banner remote-error">{error}<button onClick={() => setError('')}><X size={15}/></button></div>}
        </div>
      </div>
    </section>
  </div>
}
