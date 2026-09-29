import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ClipboardCheck, CloudMoon, Copy, Download, FileImage, Folder, FolderInput, FolderPlus, GitFork, Layers3, LayoutGrid, Lightbulb, Link2, List, ListFilter, Maximize2, Minimize2, Paperclip, Plus, Power, RefreshCw, Route, Search, Server, Settings2, Sparkles, Sprout, Trash2, Upload, X } from 'lucide-react'
import { api, type ImportPreview, type ImportResult } from './api'
import { AgentWorkspace } from './components/AgentWorkspace'
import { AttachmentPanel } from './components/AttachmentPanel'
import { AppearanceMenu, type Appearance, type Density, type UiMode } from './components/AppearanceMenu'
import { CommandPalette } from './components/CommandPalette'
import { FigureGallery } from './components/FigureGallery'
import { ExperimentPanel } from './components/ExperimentPanel'
import { DreamWorkspace } from './components/DreamWorkspace'
import { GraphView } from './components/GraphView'
import { IdeaEditor } from './components/IdeaEditor'
import { IdeaMarkdown, resolveIdeaReferencePlainText } from './components/IdeaMarkdown'
import { ImportDialog } from './components/ImportDialog'
import { LineageView } from './components/LineageView'
import { ProjectManager } from './components/ProjectManager'
import { RemotePanel } from './components/RemotePanel'
import { RelationForm } from './components/RelationForm'
import { ReviewDashboard } from './components/ReviewDashboard'
import { TagManager } from './components/TagManager'
import { tagGroupStyle, tagStyle } from './tagColors'
import type { Idea, Project, ProjectGroup, Relation, Status, Suggestion, TagInfo } from './types'

type View = 'focus' | 'cards' | 'graph' | 'lineage'
type FocusDensity = 'comfortable' | 'compact'
type Scope = { type: 'all' } | { type: 'project'; id: number } | { type: 'group'; id: number }
const statusLabels: Record<Status, string> = { seed: 'Seed', exploring: 'Exploring', promising: 'Promising', parked: 'Parked' }

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(new Date(value))
}

function TopicProjectActions({ idea, projects, onMove, onCopy }: { idea: Idea; projects: Project[]; onMove: (id: number) => Promise<void>; onCopy: (id: number) => Promise<void> }) {
  const destinations = projects.filter(project => project.id !== idea.project_id && project.system_key !== 'recycle')
  const [target, setTarget] = useState(destinations[0]?.id ?? 0)
  if (!destinations.length) return <p className="empty-small">Create another project to move or copy this topic.</p>
  return <div className="topic-project-actions">
    <select value={target} onChange={event => setTarget(Number(event.target.value))}>{destinations.map(project => <option value={project.id} key={project.id}>{project.name}</option>)}</select>
    <div><button className="button secondary small" onClick={() => onMove(target)}><FolderInput size={14}/> Move</button><button className="button secondary small" onClick={() => onCopy(target)}><Copy size={14}/> Copy</button></div>
  </div>
}

export default function App() {
  const [ideas, setIdeas] = useState<Idea[]>([])
  const [allIdeas, setAllIdeas] = useState<Idea[]>([])
  const [relations, setRelations] = useState<Relation[]>([])
  const [tags, setTags] = useState<TagInfo[]>([])
  const [tagSearch, setTagSearch] = useState('')
  const [relationTypes, setRelationTypes] = useState<string[]>([])
  const [query, setQuery] = useState('')
  const [activeTags, setActiveTags] = useState<string[]>([])
  const [status, setStatus] = useState('')
  const [relationFilter, setRelationFilter] = useState('')
  const [view, setView] = useState<View>('focus')
  const [focusDensity, setFocusDensity] = useState<FocusDensity>(() => window.localStorage.getItem('ideaminer-focus-density') === 'compact' ? 'compact' : 'comfortable')
  const [uiMode, setUiMode] = useState<UiMode>(() => window.localStorage.getItem('ideaminer-ui-mode') === 'studio' ? 'studio' : 'classic')
  const [appearance, setAppearance] = useState<Appearance>(() => {
    const saved = window.localStorage.getItem('ideaminer-appearance')
    return saved === 'dark' || saved === 'system' ? saved : 'light'
  })
  const [studioDensity, setStudioDensity] = useState<Density>(() => {
    const saved = window.localStorage.getItem('ideaminer-density')
    return saved === 'compact' || saved === 'dense' ? saved : 'comfortable'
  })
  const [systemDark, setSystemDark] = useState(() => window.matchMedia('(prefers-color-scheme: dark)').matches)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [studioNavOpen, setStudioNavOpen] = useState(false)
  const [studioInspectorOpen, setStudioInspectorOpen] = useState(true)
  const [editor, setEditor] = useState<'new' | Idea | null>(null)
  const [selected, setSelected] = useState<(Idea & { relations?: Relation[] }) | null>(null)
  const [detailFullscreen, setDetailFullscreen] = useState(false)
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [stopped, setStopped] = useState(false)
  const [projects, setProjects] = useState<Project[]>([])
  const [projectGroups, setProjectGroups] = useState<ProjectGroup[]>([])
  const [scope, setScope] = useState<Scope>({ type: 'all' })
  const [managingProjects, setManagingProjects] = useState(false)
  const [remoteOpen, setRemoteOpen] = useState(false)
  const [agentContext, setAgentContext] = useState<Idea | null | undefined>(undefined)
  const [agentDocked, setAgentDocked] = useState(() => window.localStorage.getItem('ideaminer-agent-docked') === 'true')
  const [reviewOpen, setReviewOpen] = useState(false)
  const [dreamOpen, setDreamOpen] = useState(false)
  const [dreamIdeaIds, setDreamIdeaIds] = useState<number[]>([])
  const [managingTags, setManagingTags] = useState(false)
  const importInput = useRef<HTMLInputElement>(null)
  const searchInput = useRef<HTMLInputElement>(null)
  const libraryRevision = useRef<number | null>(null)
  const selectedIdeaId = useRef<number | null>(null)
  const initialDeepLinkOpened = useRef(false)
  const [importState, setImportState] = useState<{ filename: string; data: Record<string, unknown>; preview: ImportPreview } | null>(null)

  const effectiveAppearance = appearance === 'system' ? (systemDark ? 'dark' : 'light') : appearance
  useEffect(() => { window.localStorage.setItem('ideaminer-ui-mode', uiMode) }, [uiMode])
  useEffect(() => { window.localStorage.setItem('ideaminer-appearance', appearance) }, [appearance])
  useEffect(() => { window.localStorage.setItem('ideaminer-density', studioDensity) }, [studioDensity])
  useEffect(() => { window.localStorage.setItem('ideaminer-agent-docked', String(agentDocked)) }, [agentDocked])
  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const update = () => setSystemDark(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen(value => !value)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const params = useMemo(() => {
    const value = new URLSearchParams()
    if (query) value.set('q', query)
    activeTags.forEach(tag => value.append('tag', tag))
    if (status) value.set('status', status)
    if (relationFilter) value.set('relation_type', relationFilter)
    if (scope.type === 'project') value.set('project_id', String(scope.id))
    if (scope.type === 'group') value.set('group_id', String(scope.id))
    return value
  }, [query, activeTags, status, relationFilter, scope])

  const refresh = useCallback(async () => {
    try {
      setError('')
      const tagParams = new URLSearchParams()
      if (scope.type === 'project') tagParams.set('project_id', String(scope.id))
      if (scope.type === 'group') tagParams.set('group_id', String(scope.id))
      const [filtered, all, tagList, relationList, typeList, projectList, groupList, state] = await Promise.all([
        api.ideas(params), api.ideas(new URLSearchParams()), api.tags(tagParams), api.relations(), api.relationTypes(), api.projects(), api.projectGroups(), api.libraryState(),
      ])
      libraryRevision.current = state.revision
      setIdeas(filtered); setAllIdeas(all); setTags(tagList); setActiveTags(current => {
        const valid = current.filter(name => tagList.some(tag => tag.name === name))
        return valid.length === current.length && valid.every((name, index) => name === current[index]) ? current : valid
      }); setRelations(relationList); setRelationTypes(typeList); setProjects(projectList); setProjectGroups(groupList)
    } catch (e) { setError(e instanceof Error ? e.message : 'Something went wrong') }
    finally { setLoading(false) }
  }, [params, scope])

  useEffect(() => { const timer = setTimeout(refresh, 180); return () => clearTimeout(timer) }, [refresh])
  useEffect(() => { if (!selected) setDetailFullscreen(false) }, [selected])
  useEffect(() => { selectedIdeaId.current = selected?.id ?? null }, [selected])
  useEffect(() => {
    if (!selected) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (detailFullscreen) setDetailFullscreen(false)
      else if (view !== 'focus') setSelected(null)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [selected, detailFullscreen, view])

  const openIdea = useCallback(async (id: number) => {
    const [detail, suggested] = await Promise.all([api.idea(id), api.suggestions(id)])
    setSelected(detail); setSuggestions(suggested); setStudioInspectorOpen(true)
  }, [])

  useEffect(() => {
    if (loading || view !== 'focus' || !ideas.length) return
    if (!selected || !ideas.some(idea => idea.id === selected.id)) {
      void openIdea(ideas[0].id).catch(() => setError(`Idea #${ideas[0].id} was not found`))
    }
  }, [ideas, loading, openIdea, selected, view])

  useEffect(() => {
    if (view !== 'focus' || !ideas.length) return
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      const typing = target?.matches('input, textarea, select, [contenteditable="true"]')
      if (event.key === '/' && !typing) {
        event.preventDefault()
        searchInput.current?.focus()
        return
      }
      if (typing || (event.key !== 'ArrowDown' && event.key !== 'ArrowUp' && event.key !== 'Enter')) return
      if (event.key === 'Enter' && selected) {
        event.preventDefault()
        setDetailFullscreen(true)
        return
      }
      const currentIndex = selected ? ideas.findIndex(idea => idea.id === selected.id) : -1
      const nextIndex = event.key === 'ArrowDown'
        ? Math.min(ideas.length - 1, currentIndex + 1)
        : Math.max(0, currentIndex < 0 ? 0 : currentIndex - 1)
      event.preventDefault()
      void openIdea(ideas[nextIndex].id)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [ideas, openIdea, selected, view])

  useEffect(() => {
    if (loading || initialDeepLinkOpened.current) return
    initialDeepLinkOpened.current = true
    const ideaId = Number(new URLSearchParams(window.location.search).get('idea'))
    if (Number.isInteger(ideaId) && ideaId > 0) void openIdea(ideaId).catch(() => setError(`Idea #${ideaId} was not found`))
  }, [loading, openIdea])

  useEffect(() => {
    let stopped = false
    const checkForExternalChanges = async () => {
      try {
        const state = await api.libraryState()
        if (libraryRevision.current === null) libraryRevision.current = state.revision
        else if (state.revision !== libraryRevision.current) {
          libraryRevision.current = state.revision
          await refresh()
          if (!stopped && selectedIdeaId.current) await openIdea(selectedIdeaId.current)
        }
      } catch { /* The launcher or API may be stopping. */ }
    }
    const timer = window.setInterval(() => void checkForExternalChanges(), 3000)
    return () => { stopped = true; window.clearInterval(timer) }
  }, [openIdea, refresh])

  async function saveIdea(data: { title: string; content: string; raw_text: string; status: Status; tags: string[]; project_id: number }): Promise<Idea> {
    const saved = editor && editor !== 'new' ? await api.updateIdea(editor.id, data) : await api.createIdea(data)
    await refresh()
    return saved
  }

  async function removeIdea(id: number) {
    const project = projects.find(item => item.id === selected?.project_id)
    const permanent = project?.system_key === 'recycle'
    const message = permanent ? 'Permanently delete this topic and its relations? This cannot be undone.' : 'Move this topic to recycle? You can restore it later by moving it to another project.'
    if (!window.confirm(message)) return
    await api.deleteIdea(id, permanent); setSelected(null); await refresh()
  }

  async function moveIdea(projectId: number) {
    if (!selected) return
    await api.moveIdea(selected.id, projectId); setSelected(null); await refresh()
  }

  async function copyIdea(projectId: number) {
    if (!selected) return
    await api.copyIdea(selected.id, projectId); await refresh()
  }

  async function clearCurrentProject() {
    if (scope.type !== 'project') return
    const project = projects.find(item => item.id === scope.id)
    if (!project || project.idea_count === 0) return
    const permanent = project.system_key === 'recycle'
    const warning = permanent
      ? `Permanently delete all ${project.idea_count} topics in recycle? This cannot be undone.`
      : `Move all ${project.idea_count} topics in “${project.name}” to recycle?`
    if (!window.confirm(warning)) return
    await api.clearProject(project.id); await refresh()
  }

  async function createProject(name: string, description: string, groupId: number | null, workspaceMode: 'library' | 'linked' | 'managed', workspacePath: string) {
    const project = await api.createProject({ name, description, group_id: groupId, workspace_mode: workspaceMode, workspace_path: workspacePath })
    await refresh(); setScope({ type: 'project', id: project.id }); setManagingProjects(false)
  }

  async function createProjectGroup(name: string) {
    await api.createProjectGroup(name); await refresh()
  }

  async function chooseImportFile(file: File | undefined) {
    if (!file) return
    try {
      setError('')
      const parsed: unknown = JSON.parse(await file.text())
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('The selected file is not an IdeaMiner JSON export')
      const data = parsed as Record<string, unknown>
      const preview = await api.previewImport(data)
      setImportState({ filename: file.name, data, preview })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not read that import file')
    }
  }

  async function runImport(duplicateStrategy: 'skip' | 'copy' | 'update', projectStrategy: 'merge' | 'rename'): Promise<ImportResult> {
    if (!importState) throw new Error('No import is ready')
    const result = await api.importJson(importState.data, duplicateStrategy, projectStrategy)
    await refresh()
    return result
  }

  async function createRelation(target: number, type: string, note: string) {
    if (!selected) return
    try { await api.createRelation({ source_id: selected.id, target_id: target, relation_type: type, note }); await refresh(); await openIdea(selected.id) }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not create relation') }
  }

  async function changeIdeaStatus(next: Status) {
    if (!selected || selected.status === next) return
    try {
      await api.updateIdea(selected.id, { title: selected.title, content: selected.content, status: next, tags: selected.tags, expected_updated_at: selected.updated_at })
      await refresh(); await openIdea(selected.id)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not update status') }
  }

  function addDreamIdea(id: number) {
    if (!allIdeas.some(idea => idea.id === id)) return
    setDreamIdeaIds(current => current.includes(id) || current.length >= 8 ? current : [...current, id])
  }

  function changeFocusDensity(next: FocusDensity) {
    setFocusDensity(next)
    window.localStorage.setItem('ideaminer-focus-density', next)
  }

  function switchView(next: View) {
    setDetailFullscreen(false)
    if (next !== 'focus') setSelected(null)
    setView(next)
  }

  function runStudioCommand(action: string) {
    if (action === 'review') setReviewOpen(true)
    else if (action === 'graph' || action === 'lineage' || action === 'focus' || action === 'cards') switchView(action)
    else if (action === 'agent') setAgentContext(null)
    else if (action === 'dream') setDreamOpen(true)
    else if (action === 'projects') setManagingProjects(true)
    else if (action === 'tags') setManagingTags(true)
    else if (action === 'import') importInput.current?.click()
    else if (action === 'export-json') window.location.href = '/api/export/json'
    else if (action === 'export-md') window.location.href = '/api/export/markdown'
  }

  const clearFilters = () => { setQuery(''); setActiveTags([]); setStatus(''); setRelationFilter('') }
  const filtered = Boolean(query || activeTags.length || status || relationFilter)
  const currentProject = scope.type === 'project' ? projects.find(project => project.id === scope.id) : undefined
  const currentGroup = scope.type === 'group' ? projectGroups.find(group => group.id === scope.id) : undefined
  const defaultProjectId = currentProject?.system_key !== 'recycle' && currentProject ? currentProject.id : projects.find(project => project.system_key === 'random_chat')?.id ?? projects[0]?.id ?? 0
  const scopeTitle = currentProject?.system_key === 'recycle' ? 'Recycle' : currentProject?.name ?? currentGroup?.name ?? 'All ideas'
  const visibleTags = (tagSearch.trim() ? tags.filter(tag => tag.name.includes(tagSearch.trim().toLowerCase()) || tag.group_name.toLowerCase().includes(tagSearch.trim().toLowerCase())) : tags.slice(0, 16))
  const tagsByGroup = visibleTags.reduce<Record<string, TagInfo[]>>((groups, tag) => { const group = tag.group_name || 'General'; (groups[group] ??= []).push(tag); return groups }, {})
  const tagGroupByName = new Map(tags.map(tag => [tag.name, tag.group_name]))
  const styleForTag = (name: string) => tagStyle(name, tagGroupByName.get(name) || '')

  async function quitApplication() {
    if (!window.confirm('Quit IdeaMiner and stop its local servers?')) return
    try {
      await api.quit()
      setStopped(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not stop IdeaMiner')
    }
  }

  return <div className={`app-shell ${agentContext !== undefined && agentDocked ? 'agent-is-docked' : ''} ${agentContext !== undefined && agentDocked && selected && (view !== 'focus' || detailFullscreen) ? 'agent-has-detail-docked' : ''}`} data-ui-mode={uiMode} data-appearance={effectiveAppearance} data-density={studioDensity}>
    <header className="topbar">
      <div className="brand"><div className="brand-mark"><Sprout size={22}/></div><div><strong>IdeaMiner</strong><span>research idea garden</span></div></div>
      <button className="studio-search-trigger" onClick={() => setPaletteOpen(true)}><Search size={16}/><span>Search ideas or commands…</span><kbd>Ctrl K</kbd></button>
      <div className="top-actions">
        <button className="button agent-button" onClick={() => setAgentContext(null)}><Sparkles size={16}/> Agent</button>
        <button className="button dream-button" onClick={() => setDreamOpen(true)}><CloudMoon size={16}/> Dream{dreamIdeaIds.length ? ` · ${dreamIdeaIds.length}` : ''}</button>
        <button className="button ghost" onClick={() => setReviewOpen(true)}><ClipboardCheck size={16}/> Review</button>
        <button className="button projects-button" onClick={() => setManagingProjects(true)}><FolderPlus size={16}/> Projects</button>
        <button className="button ghost remote-button" onClick={() => setRemoteOpen(true)}><Server size={16}/> Remote</button>
        <button className="button import-button" onClick={() => importInput.current?.click()}><Upload size={16}/> Import</button>
        <input className="hidden-file-input" ref={importInput} type="file" accept="application/json,.json" onChange={event => { void chooseImportFile(event.target.files?.[0]); event.target.value = '' }}/>
        <div className="export-menu"><button className="button ghost"><Download size={16}/> Export</button><div><a href="/api/export/markdown" download>Markdown</a><a href="/api/export/json" download>JSON</a></div></div>
        <button className="button quit-button" onClick={quitApplication} title="Quit IdeaMiner"><Power size={16}/> Quit</button>
        <button className="button primary" onClick={() => setEditor('new')}><Plus size={17}/> New idea</button>
        <button className="button studio-capture" onClick={() => setEditor('new')}><Plus size={16}/> Capture</button>
        <AppearanceMenu uiMode={uiMode} appearance={appearance} density={studioDensity} onUiMode={setUiMode} onAppearance={setAppearance} onDensity={setStudioDensity}/>
      </div>
    </header>

    <main className={studioNavOpen ? 'studio-nav-open' : ''}>
      <button className="studio-nav-backdrop" aria-label="Close navigation" onClick={() => setStudioNavOpen(false)}/>
      <aside className={`sidebar ${studioNavOpen ? 'studio-nav-open' : ''}`}>
        <div className="studio-sidebar-nav">
          <div className="studio-nav-label">WORKSPACE</div>
          {([['focus', 'Focus', List], ['cards', 'Cards', LayoutGrid], ['graph', 'Graph', GitFork], ['lineage', 'Lineage', Route]] as const).map(([id, label, Icon]) => <button key={id} className={view === id ? 'active' : ''} onClick={() => { switchView(id); setStudioNavOpen(false) }}><Icon size={16}/>{label}{id === 'focus' && <span>{ideas.length}</span>}</button>)}
          <div className="studio-nav-label">WORKFLOW</div>
          <button onClick={() => { setReviewOpen(true); setStudioNavOpen(false) }}><ClipboardCheck size={16}/>Review</button>
          <button onClick={() => { setAgentContext(null); setStudioNavOpen(false) }}><Sparkles size={16}/>Agent</button>
          <button onClick={() => { setDreamOpen(true); setStudioNavOpen(false) }}><CloudMoon size={16}/>Dream</button>
          <button onClick={() => { setManagingProjects(true); setStudioNavOpen(false) }}><FolderPlus size={16}/>Manage projects</button>
          <button onClick={() => { setRemoteOpen(true); setStudioNavOpen(false) }}><Server size={16}/>Remote sync</button>
          <button onClick={() => { setManagingTags(true); setStudioNavOpen(false) }}><Settings2 size={16}/>Manage tags</button>
        </div>
        <div className="sidebar-label project-label"><Folder size={14}/> PROJECTS <button onClick={() => setManagingProjects(true)} title="Create project or group"><Plus size={14}/></button></div>
        <nav className="project-nav">
          <button className={scope.type === 'all' ? 'active' : ''} onClick={() => setScope({ type: 'all' })}><LayoutGrid size={14}/><span>All active ideas</span><small>{projects.filter(p => p.system_key !== 'recycle').reduce((total, p) => total + p.idea_count, 0)}</small></button>
          {projectGroups.map(group => <div className="project-group" key={group.id}>
            <button className={scope.type === 'group' && scope.id === group.id ? 'active' : ''} onClick={() => setScope({ type: 'group', id: group.id })}><Layers3 size={14}/><span>{group.name}</span><small>{group.idea_count}</small></button>
            {projects.filter(project => project.group_id === group.id).map(project => <button className={`project-child ${scope.type === 'project' && scope.id === project.id ? 'active' : ''}`} onClick={() => setScope({ type: 'project', id: project.id })} key={project.id}><span>{project.name}</span><small>{project.idea_count}</small></button>)}
          </div>)}
          {projects.filter(project => !project.group_id && project.system_key !== 'recycle').map(project => <button className={scope.type === 'project' && scope.id === project.id ? 'active' : ''} onClick={() => setScope({ type: 'project', id: project.id })} key={project.id}><Folder size={14}/><span>{project.name}</span><small>{project.idea_count}</small></button>)}
          {projects.filter(project => project.system_key === 'recycle').map(project => <button className={`recycle-link ${scope.type === 'project' && scope.id === project.id ? 'active' : ''}`} onClick={() => setScope({ type: 'project', id: project.id })} key={project.id}><Trash2 size={14}/><span>Recycle</span><small>{project.idea_count}</small></button>)}
        </nav>
        <div className="sidebar-label filter-label"><ListFilter size={14}/> FILTERS</div>
        <label className="search"><Search size={17}/><input ref={searchInput} value={query} onChange={e => setQuery(e.target.value)} placeholder="Search every thought…"/>{query && <button onClick={() => setQuery('')}><X size={14}/></button>}</label>
        <section><h3>Stage</h3>{(['seed', 'exploring', 'promising', 'parked'] as Status[]).map(item => <button key={item} onClick={() => setStatus(status === item ? '' : item)} className={`filter-row ${status === item ? 'active' : ''}`}><span className={`status-dot ${item}`}/>{statusLabels[item]}<span>{allIdeas.filter(i => i.status === item).length}</span></button>)}</section>
        <section><h3 className="tag-panel-title"><span>Tags</span><span><button title="Refresh tags" aria-label="Refresh tags" onClick={() => void refresh()}><RefreshCw size={13}/></button><button title="Manage tags and open tag map" aria-label="Manage tags and open tag map" onClick={() => setManagingTags(true)}><Settings2 size={13}/></button></span></h3><label className="tag-search"><Search size={13}/><input value={tagSearch} onChange={event => setTagSearch(event.target.value)} placeholder="Filter tags"/>{tagSearch && <button onClick={() => setTagSearch('')}><X size={12}/></button>}</label><div className="tag-filters">{Object.entries(tagsByGroup).map(([group, grouped]) => <div className="tag-filter-group" key={group}><small><i style={tagGroupStyle(group)}/>{group}</small><div>{grouped.map(tag => <button key={tag.name} style={tagStyle(tag.name, tag.group_name)} className={activeTags.includes(tag.name) ? 'active' : ''} onClick={() => setActiveTags(activeTags.includes(tag.name) ? activeTags.filter(t => t !== tag.name) : [...activeTags, tag.name])}>#{tag.name}<span>{tag.count}</span></button>)}</div></div>)}</div>{!tags.length ? <p className="empty-small">No tags yet.</p> : !tagSearch && tags.length > 16 ? <button className="more-tags" onClick={() => setManagingTags(true)}>Showing the 16 most-used tags · Manage all {tags.length}</button> : null}</section>
        <section><h3>Connection</h3><select className="sidebar-select" value={relationFilter} onChange={e => setRelationFilter(e.target.value)}><option value="">Any relation type</option>{relationTypes.map(type => <option key={type}>{type}</option>)}</select></section>
        {filtered && <button className="clear-filters" onClick={clearFilters}><X size={14}/> Clear all filters</button>}
        <div className="storage-note"><span className="pulse"/><div><strong>Stored locally</strong><small>SQLite is your source of truth</small></div></div>
      </aside>

      <section className="workspace">
        <div className="studio-mobile-toolbar"><button className="icon-button" aria-label="Open navigation" onClick={() => setStudioNavOpen(true)}><List size={18}/></button><select aria-label="Select workspace view" value={view} onChange={event => switchView(event.target.value as View)}><option value="focus">Focus</option><option value="cards">Cards</option><option value="graph">Graph</option><option value="lineage">Lineage</option></select></div>
        <select className="mobile-project-select" value={scope.type === 'all' ? 'all' : `${scope.type}:${scope.id}`} onChange={event => { const [type, id] = event.target.value.split(':'); setScope(type === 'all' ? { type: 'all' } : { type: type as 'project' | 'group', id: Number(id) }) }}><option value="all">All active ideas</option>{projectGroups.map(group => <option value={`group:${group.id}`} key={`g${group.id}`}>Group: {group.name}</option>)}{projects.map(project => <option value={`project:${project.id}`} key={`p${project.id}`}>{project.system_key === 'recycle' ? 'Recycle' : project.name}</option>)}</select>
        <div className="workspace-head"><div><p className="eyebrow">{scope.type === 'group' ? 'PROJECT GROUP' : currentProject?.system_key === 'recycle' ? 'RECYCLE BIN' : scope.type === 'project' ? 'PROJECT' : 'YOUR KNOWLEDGE GARDEN'}</p><h1>{query ? `Results in ${scopeTitle}` : activeTags.length ? `${scopeTitle} · #${activeTags[0]}` : scopeTitle}</h1><p>{ideas.length} {ideas.length === 1 ? 'thought' : 'thoughts'} · {relations.filter(r => ideas.some(i => i.id === r.source_id) && ideas.some(i => i.id === r.target_id)).length} visible connections</p></div><div className="workspace-actions">{currentProject && ideas.length > 0 && <button className="button bulk-delete" onClick={clearCurrentProject}><Trash2 size={15}/>{currentProject.system_key === 'recycle' ? 'Empty recycle' : 'Recycle all'}</button>}<div className="view-toggle"><button className={view === 'focus' ? 'active' : ''} onClick={() => switchView('focus')}><List size={16}/> Focus</button><button className={view === 'cards' ? 'active' : ''} onClick={() => switchView('cards')}><LayoutGrid size={16}/> Cards</button><button className={view === 'graph' ? 'active' : ''} onClick={() => switchView('graph')}><GitFork size={16}/> Graph</button><button className={view === 'lineage' ? 'active' : ''} onClick={() => switchView('lineage')}><Route size={16}/> Lineage</button></div></div></div>
        {error && <div className="error-banner">{error}<button onClick={() => setError('')}><X size={15}/></button></div>}
        {loading ? <div className="loading"><Sprout/> Growing your garden…</div> : ideas.length === 0 ? <div className="empty-state"><div>{currentProject?.system_key === 'recycle' ? <Trash2 size={30}/> : <Lightbulb size={30}/>}</div><h2>{filtered ? 'No ideas match' : currentProject?.system_key === 'recycle' ? 'Recycle is empty' : 'Plant your first idea'}</h2><p>{filtered ? 'Try widening your filters or searching another phrase.' : currentProject?.system_key === 'recycle' ? 'Deleted topics will wait here until you restore or permanently remove them.' : 'Capture a research question, a surprising connection, or a half-formed hunch.'}</p>{currentProject?.system_key !== 'recycle' && <button className="button primary" onClick={filtered ? clearFilters : () => setEditor('new')}>{filtered ? 'Clear filters' : <><Plus size={17}/> Capture an idea</>}</button>}</div> : view === 'graph' ? <GraphView ideas={ideas} relations={relations} onSelect={openIdea}/> : view === 'lineage' ? <LineageView ideas={ideas} relations={relations} onSelect={openIdea}/> : view === 'focus' ? <div className={`focus-browser ${focusDensity} studio-${studioDensity}`}>
          <section className="focus-list-pane">
            <header><div><strong>Idea navigator</strong><span>{ideas.length} visible · ↑↓ to move · Enter to expand</span></div><div className="density-toggle" aria-label="List density"><button className={focusDensity === 'comfortable' ? 'active' : ''} onClick={() => changeFocusDensity('comfortable')}>Roomy</button><button className={focusDensity === 'compact' ? 'active' : ''} onClick={() => changeFocusDensity('compact')}>Compact</button></div></header>
            <div className="focus-list" role="list">{ideas.map(idea => {
              const project = projects.find(item => item.id === idea.project_id)
              const connectionCount = relations.filter(relation => relation.source_id === idea.id || relation.target_id === idea.id).length
              return <article role="listitem" tabIndex={0} draggable className={`focus-row ${selected?.id === idea.id ? 'selected' : ''} ${dreamIdeaIds.includes(idea.id) ? 'dream-selected' : ''}`} key={idea.id} onDragStart={event => { event.dataTransfer.effectAllowed = 'copy'; event.dataTransfer.setData('application/x-ideaminer-idea', String(idea.id)) }} onClick={() => void openIdea(idea.id)}>
                <span className={`status-dot ${idea.status}`}/><div className="focus-row-main"><div><strong>{idea.title}</strong><time>{formatDate(idea.updated_at)}</time></div><p>{resolveIdeaReferencePlainText(idea.content || 'No notes yet.', allIdeas)}</p><footer><span>{project?.name ?? 'Unknown project'}</span><div>{idea.tags.slice(0, 2).map(tag => <span className="tag" style={styleForTag(tag)} key={tag}>#{tag}</span>)}{idea.tags.length > 2 && <small>+{idea.tags.length - 2}</small>}</div><span><Link2 size={11}/>{connectionCount}</span></footer></div>
              </article>
            })}</div>
          </section>
          <aside className={`focus-preview ${studioInspectorOpen ? 'studio-inspector-open' : ''}`}>{selected ? <>
            <header><label className={`status-pill status-picker ${selected.status}`}><span/><select value={selected.status} onChange={event => void changeIdeaStatus(event.target.value as Status)} aria-label="Change idea status">{(Object.keys(statusLabels) as Status[]).map(value => <option value={value} key={value}>{statusLabels[value]}</option>)}</select></label><div><button className="icon-button studio-inspector-close" aria-label="Close idea inspector" onClick={() => setStudioInspectorOpen(false)}><X size={16}/></button><button className="icon-button" title="Open full screen" aria-label="Open idea full screen" onClick={() => setDetailFullscreen(true)}><Maximize2 size={16}/></button></div></header>
            <p className="focus-context"><Folder size={13}/>{projects.find(project => project.id === selected.project_id)?.name ?? 'Unknown project'}<span>Updated {formatDate(selected.updated_at)}</span></p>
            <h2>{selected.title}</h2><div className="detail-tags">{selected.tags.map(tag => <span className="tag" style={styleForTag(tag)} key={tag}>#{tag}</span>)}</div>
            <div className="markdown focus-markdown"><IdeaMarkdown content={selected.content || '_No notes yet._'} ideas={allIdeas} attachments={selected.attachments} onIdeaSelect={openIdea} onFileOpen={id => void api.openAttachment(id)}/></div>
            {!detailFullscreen && <FigureGallery idea={selected} onChanged={async () => { await refresh(); await openIdea(selected.id) }}/>}
            {projects.find(project => project.id === selected.project_id)?.system_key !== 'recycle' && <div className="focus-actions"><button className="button agent-launch" onClick={() => setAgentContext(selected)}><Sparkles size={15}/> Agent</button><button className="button secondary" onClick={() => setEditor(selected)}>Edit</button><button className="button secondary" onClick={() => setDetailFullscreen(true)}><Maximize2 size={15}/> Full detail</button></div>}
            <section className="focus-connections"><h3><Link2 size={14}/> Connections</h3>{selected.relations?.length ? selected.relations.slice(0, 5).map(relation => { const otherId = relation.source_id === selected.id ? relation.target_id : relation.source_id; const otherTitle = relation.source_id === selected.id ? relation.target_title : relation.source_title; return <button key={relation.id} onClick={() => void openIdea(otherId)}><span>{relation.relation_type}</span><strong>{otherTitle}</strong></button> }) : <p className="empty-small">No recorded connections yet.</p>}</section>
            {projects.find(project => project.id === selected.project_id)?.system_key !== 'recycle' && <ExperimentPanel ideaId={selected.id} ideas={allIdeas} attachments={selected.attachments} onChanged={refresh}/>}
            <section className="focus-connections"><h3><Sprout size={14}/> Related ideas</h3>{suggestions.length ? suggestions.slice(0, 4).map(item => <button key={item.id} onClick={() => void openIdea(item.id)}><strong>{item.title}</strong><span>{item.reason}</span></button>) : <p className="empty-small">Add tags or richer notes to surface connections.</p>}</section>
          </> : <div className="focus-placeholder"><Sprout size={26}/><strong>Select an idea</strong><span>Its notes and connections will stay here while you browse.</span></div>}</aside>
        </div> : <div className="idea-grid">{ideas.map(idea => <article draggable className={`idea-card ${dreamIdeaIds.includes(idea.id) ? 'dream-selected' : ''}`} key={idea.id} onDragStart={event => { event.dataTransfer.effectAllowed = 'copy'; event.dataTransfer.setData('application/x-ideaminer-idea', String(idea.id)) }} onClick={() => openIdea(idea.id)}>
          <div className="card-top"><span className={`status-pill ${idea.status}`}><span/>{statusLabels[idea.status]}</span><time>{formatDate(idea.updated_at)}</time></div>
          <h2>{idea.title}</h2><p>{resolveIdeaReferencePlainText(idea.content || 'No notes yet.', allIdeas)}</p>
          <footer><div>{idea.tags.slice(0, 3).map(tag => <span className="tag" style={styleForTag(tag)} key={tag}>#{tag}</span>)}</div>{(idea.figure_count ?? 0) > 0 && <span className="figure-count" title={`${idea.figure_count} figure${idea.figure_count === 1 ? '' : 's'}`}><FileImage size={13}/>{idea.figure_count}</span>}<span className="connection-count"><Link2 size={14}/>{relations.filter(r => r.source_id === idea.id || r.target_id === idea.id).length}</span></footer>
        </article>)}</div>}
      </section>
    </main>

    {editor && <IdeaEditor idea={editor === 'new' ? null : editor} projects={projects} defaultProjectId={defaultProjectId} ideas={allIdeas} onClose={() => setEditor(null)} onSave={saveIdea}/>}
    {managingProjects && <ProjectManager groups={projectGroups} onClose={() => setManagingProjects(false)} onCreateProject={createProject} onCreateGroup={createProjectGroup}/>}
    {remoteOpen && <RemotePanel projects={projects} onClose={() => setRemoteOpen(false)}/>}
    {importState && <ImportDialog filename={importState.filename} preview={importState.preview} onClose={() => setImportState(null)} onImport={runImport}/>}
    {managingTags && <TagManager visibleIdeaIds={ideas.map(idea => idea.id)} scope={scope} onClose={() => setManagingTags(false)} onChanged={refresh} onFilterTag={name => { setActiveTags([name]); setManagingTags(false) }}/>}
    {selected && (view !== 'focus' || detailFullscreen) && <div className={`drawer-backdrop ${detailFullscreen ? 'detail-fullscreen-backdrop' : ''}`} onMouseDown={e => e.target === e.currentTarget && (detailFullscreen ? setDetailFullscreen(false) : setSelected(null))}><aside className={`detail-drawer ${detailFullscreen ? 'fullscreen' : ''}`}>
      <header><label className={`status-pill status-picker ${selected.status}`}><span/><select value={selected.status} onChange={event => void changeIdeaStatus(event.target.value as Status)} aria-label="Change idea status">{(Object.keys(statusLabels) as Status[]).map(value => <option value={value} key={value}>{statusLabels[value]}</option>)}</select></label><div><button className="icon-button" aria-label={detailFullscreen ? 'Restore idea drawer' : 'View idea full screen'} title={detailFullscreen ? 'Restore drawer' : 'View full screen'} onClick={() => setDetailFullscreen(value => !value)}>{detailFullscreen ? <Minimize2 size={17}/> : <Maximize2 size={17}/>}</button><button className="icon-button danger" title={projects.find(project => project.id === selected.project_id)?.system_key === 'recycle' ? 'Delete permanently' : 'Move to recycle'} onClick={() => removeIdea(selected.id)}><Trash2 size={17}/></button><button className="icon-button" aria-label="Close idea" onClick={() => detailFullscreen && view === 'focus' ? setDetailFullscreen(false) : setSelected(null)}><X size={20}/></button></div></header>
      <h1>{selected.title}</h1><div className="detail-tags">{selected.tags.map(t => <span className="tag" style={styleForTag(t)} key={t}>#{t}</span>)}</div>
      <div className="topic-location"><Folder size={14}/>{projects.find(project => project.id === selected.project_id)?.name ?? 'Unknown project'}</div>
      <div className="markdown"><IdeaMarkdown content={selected.content || '_No notes yet._'} ideas={allIdeas} attachments={selected.attachments} onIdeaSelect={openIdea} onFileOpen={id => void api.openAttachment(id)}/></div>
      {projects.find(project => project.id === selected.project_id)?.system_key !== 'recycle' && <><button className="button agent-launch wide" onClick={() => { setAgentContext(selected); if (view === 'focus') setDetailFullscreen(false); else setSelected(null) }}><Sparkles size={16}/> Explore with Agent</button><button className="button secondary wide" onClick={() => { setEditor(selected); if (view === 'focus') setDetailFullscreen(false); else setSelected(null) }}>Edit idea</button></>}
      <section className="detail-section"><h3><FolderInput size={16}/> Project actions</h3><TopicProjectActions idea={selected} projects={projects} onMove={moveIdea} onCopy={copyIdea}/></section>
      <section className="detail-section"><FigureGallery idea={selected} onChanged={async () => { await refresh(); await openIdea(selected.id) }}/></section>
      <section className="detail-section"><h3><Paperclip size={16}/> Local files</h3><AttachmentPanel idea={selected} project={projects.find(project => project.id === selected.project_id)} onChanged={async () => { await refresh(); await openIdea(selected.id) }}/></section>
      <section className="detail-section"><h3><Link2 size={16}/> Connections</h3><RelationForm idea={selected} ideas={allIdeas} types={relationTypes} onCreate={createRelation}/>{selected.relations?.map(relation => { const other = relation.source_id === selected.id ? relation.target_title : relation.source_title; return <div className="relation-item" key={relation.id}><div><span>{relation.relation_type}</span><strong>{other}</strong>{relation.note && <small>{relation.note}</small>}</div><button onClick={async () => { await api.deleteRelation(relation.id); await refresh(); await openIdea(selected.id) }}><X size={14}/></button></div> })}</section>
      {projects.find(project => project.id === selected.project_id)?.system_key !== 'recycle' && <ExperimentPanel ideaId={selected.id} ideas={allIdeas} attachments={selected.attachments} onChanged={refresh}/>}
      <section className="detail-section"><h3><Sprout size={16}/> Related ideas</h3>{suggestions.length ? suggestions.map(item => <button className="suggestion" key={item.id} onClick={() => openIdea(item.id)}><strong>{item.title}</strong><span>{item.reason}</span></button>) : <p className="empty-small">Add tags or richer notes to surface connections.</p>}</section>
      <details className="original"><summary>Original capture</summary><pre>{selected.raw_text}</pre></details>
    </aside></div>}
    {agentContext !== undefined && <AgentWorkspace scope={scope} contextIdea={agentContext} ideas={allIdeas} projects={projects} groups={projectGroups} isDocked={agentDocked} onDockToggle={() => setAgentDocked(current => !current)} onClose={() => setAgentContext(undefined)} onChanged={refresh} onIdeaSelect={id => { setAgentContext(undefined); void openIdea(id) }}/>}
    {reviewOpen && <ReviewDashboard scope={scope} scopeTitle={scopeTitle} onClose={() => setReviewOpen(false)} onChanged={refresh} onIdeaSelect={id => { setReviewOpen(false); void openIdea(id) }} onLineageSelect={id => { setReviewOpen(false); switchView('lineage'); void openIdea(id) }} onDream={ids => { setDreamIdeaIds(ids); setReviewOpen(false); setDreamOpen(true) }}/>}
    {dreamOpen && <DreamWorkspace ideaIds={dreamIdeaIds} ideas={allIdeas} projects={projects} onClose={() => setDreamOpen(false)} onRemove={id => setDreamIdeaIds(current => current.filter(item => item !== id))} onChanged={refresh} onIdeaSelect={id => { setDreamOpen(false); void openIdea(id) }} onOpenAgent={() => { setDreamOpen(false); setAgentContext(null) }}/>}
    <button className={`dream-dock ${dreamIdeaIds.length ? 'ready' : ''}`} onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); addDreamIdea(Number(event.dataTransfer.getData('application/x-ideaminer-idea'))) }} onClick={() => setDreamOpen(true)}><CloudMoon size={18}/><span>{dreamIdeaIds.length ? `${dreamIdeaIds.length} idea${dreamIdeaIds.length === 1 ? '' : 's'} ready to Dream` : 'Drag ideas here to Dream'}</span></button>
    {stopped && <div className="shutdown-screen"><div className="shutdown-card"><div className="brand-mark"><Sprout size={25}/></div><p className="eyebrow">SHUTDOWN COMPLETE</p><h1>IdeaMiner has stopped.</h1><p>Your ideas are safely stored in SQLite. You can close this browser tab and double-click <code>start-ideaminer.bat</code> whenever you want to return.</p></div></div>}
    {paletteOpen && <CommandPalette ideas={allIdeas} onClose={() => setPaletteOpen(false)} onOpenIdea={id => { void openIdea(id); switchView('focus') }} onCapture={() => { switchView('focus'); setEditor('new') }} onAction={runStudioCommand} uiMode={uiMode} onSwitchMode={() => setUiMode(value => value === 'studio' ? 'classic' : 'studio')} onToggleAppearance={() => setAppearance(value => value === 'dark' || (value === 'system' && systemDark) ? 'light' : 'dark')}/>}
  </div>
}
