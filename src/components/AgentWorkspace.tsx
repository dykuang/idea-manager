import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, FileText, GitBranch, Globe2, KeyRound, LoaderCircle, Paperclip, Save, Send, ShieldCheck, Sparkles, X } from 'lucide-react'
import { api } from '../api'
import { IdeaMarkdown } from './IdeaMarkdown'
import type { AgentMessage, AgentMode, AgentProposal, AgentProvider, AgentProviderOption, AgentRunResult, AgentRunSaveResult, AgentStatus, Attachment, Idea, Project, ProjectGroup, ReasoningEffort } from '../types'

type Scope = { type: 'all' } | { type: 'project'; id: number } | { type: 'group'; id: number }

const modes: { id: AgentMode; label: string }[] = [
  { id: 'explore', label: 'Explore' },
  { id: 'elaborate', label: 'Elaborate' },
  { id: 'critique', label: 'Critique' },
  { id: 'connect', label: 'Connect' },
  { id: 'synthesize', label: 'Synthesize' },
]

function payloadPreview(proposal: AgentProposal) {
  const data = proposal.payload
  if (proposal.action_type === 'create_relation') return `${String(data.source_id)} → ${String(data.target_id)} · ${String(data.relation_type || 'related-to')}`
  const tags = Array.isArray(data.tags) ? data.tags.join(', ') : ''
  return [String(data.idea_title || ''), String(data.status || ''), tags && `#${tags.replaceAll(', ', ' #')}`].filter(Boolean).join(' · ')
}

export function AgentWorkspace({ scope, contextIdea, ideas, projects, groups, onClose, onChanged, onIdeaSelect }: {
  scope: Scope
  contextIdea: Idea | null
  ideas: Idea[]
  projects: Project[]
  groups: ProjectGroup[]
  onClose: () => void
  onChanged: () => Promise<void>
  onIdeaSelect: (id: number) => void
}) {
  const [status, setStatus] = useState<AgentStatus | null>(null)
  const [mode, setMode] = useState<AgentMode>(contextIdea ? 'elaborate' : 'explore')
  const [prompt, setPrompt] = useState('')
  const [chatMessages, setChatMessages] = useState<AgentMessage[]>([])
  const [sessionScope, setSessionScope] = useState<Scope>(scope.type === 'project' && projects.find(item => item.id === scope.id)?.system_key === 'recycle' ? { type: 'all' } : scope)
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [provider, setProvider] = useState<AgentProvider>('openai')
  const [connectionModel, setConnectionModel] = useState('gpt-5.6-luna')
  const [baseUrl, setBaseUrl] = useState('https://api.openai.com/v1')
  const [reasoningEffort, setReasoningEffort] = useState<ReasoningEffort>('medium')
  const [connectionReasoningEffort, setConnectionReasoningEffort] = useState<ReasoningEffort>('medium')
  const [rememberApiKey, setRememberApiKey] = useState(true)
  const [editingConnection, setEditingConnection] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [webSearch, setWebSearch] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<AgentRunResult | null>(null)
  const [resultMode, setResultMode] = useState<AgentMode | null>(null)
  const [savingResult, setSavingResult] = useState<'update_original' | 'create_child' | null>(null)
  const [savedResult, setSavedResult] = useState<AgentRunSaveResult | null>(null)
  const [availableFiles, setAvailableFiles] = useState<Attachment[]>([])
  const [selectedFileIds, setSelectedFileIds] = useState<number[]>([])
  const chatEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [chatMessages, running])

  useEffect(() => {
    api.agentStatus().then(value => {
      setStatus(value); setProvider(value.provider); setModel(value.default_model)
      setConnectionModel(value.default_model); setBaseUrl(value.base_url)
      setReasoningEffort(value.reasoning_effort); setConnectionReasoningEffort(value.reasoning_effort)
      setRememberApiKey(value.credential_store_available)
    }).catch(error => setError(error instanceof Error ? error.message : 'Could not inspect agent configuration'))
  }, [])

  useEffect(() => {
    const params = new URLSearchParams()
    if (contextIdea) params.set('idea_id', String(contextIdea.id))
    else if (sessionScope.type === 'project') params.set('project_id', String(sessionScope.id))
    else if (sessionScope.type === 'group') params.set('group_id', String(sessionScope.id))
    api.attachments(params).then(files => { setAvailableFiles(files); setSelectedFileIds([]) }).catch(() => setAvailableFiles([]))
  }, [contextIdea?.id, sessionScope.type, sessionScope.type === 'all' ? null : sessionScope.id])

  const contextName = useMemo(() => {
    const projectContext = sessionScope.type === 'project' ? `Project: ${projects.find(item => item.id === sessionScope.id)?.name ?? 'Unknown'}`
      : sessionScope.type === 'group' ? `Group: ${groups.find(item => item.id === sessionScope.id)?.name ?? 'Unknown'}`
        : 'All active projects'
    if (contextIdea) return `${projectContext} · ${contextIdea.title}`
    if (sessionScope.type === 'project') return projectContext
    if (sessionScope.type === 'group') return projectContext
    return 'All active ideas (up to 40 recent ideas)'
  }, [contextIdea, groups, projects, sessionScope])

  const activeProfile = status?.providers.find(item => item.id === provider) ?? null
  const keyReady = Boolean(apiKey.trim() || activeProfile?.configured || !activeProfile?.api_key_required)

  function chooseMode(next: AgentMode) {
    setMode(next)
  }

  function loadProfile(option: AgentProviderOption, nextStatus?: AgentStatus) {
    setProvider(option.id); setConnectionModel(option.model); setBaseUrl(option.base_url)
    setConnectionReasoningEffort(option.reasoning_effort); setModel(option.model); setReasoningEffort(option.reasoning_effort)
    setApiKey(''); setEditingConnection(!option.configured)
    if (!option.web_search_supported) setWebSearch(false)
    if (nextStatus) setStatus(nextStatus)
  }

  async function chooseProvider(next: AgentProvider) {
    setError('')
    try {
      const nextStatus = await api.activateAgentProvider(next)
      const option = nextStatus.providers.find(item => item.id === next)
      if (option) loadProfile(option, nextStatus)
    } catch (error) { setError(error instanceof Error ? error.message : 'Could not switch providers') }
  }

  async function run() {
    if (!prompt.trim() || running) return
    const userMessage = prompt.trim()
    setRunning(true); setError(''); setResult(null); setSavedResult(null); setResultMode(null)
    try {
      const next = await api.runAgent({
        prompt: userMessage, conversation: chatMessages.slice(-12), mode,
        scope_type: sessionScope.type, scope_id: sessionScope.type === 'all' ? null : sessionScope.id,
        idea_id: contextIdea?.id ?? null, model, reasoning_effort: reasoningEffort, web_search: webSearch, attachment_ids: selectedFileIds,
      })
      setResult(next); setResultMode(mode)
      setChatMessages(current => [...current, { role: 'user', content: userMessage }, { role: 'assistant', content: next.answer }])
      setPrompt('')
    } catch (error) {
      setError(error instanceof Error ? error.message : 'The agent could not complete this request')
    } finally { setRunning(false) }
  }

  async function connect() {
    const profile = status?.providers.find(item => item.id === provider)
    if ((profile?.api_key_required && !apiKey.trim() && !profile.configured) || !connectionModel.trim() || !baseUrl.trim()) return
    setConnecting(true); setError('')
    try {
      const next = await api.configureAgent({ provider, api_key: apiKey, model: connectionModel, base_url: baseUrl, reasoning_effort: connectionReasoningEffort, remember_api_key: rememberApiKey })
      setApiKey(''); setStatus(next); setProvider(next.provider); setModel(next.default_model); setReasoningEffort(next.reasoning_effort); setBaseUrl(next.base_url); setEditingConnection(false)
    } catch (error) { setError(error instanceof Error ? error.message : 'Could not save the connection') }
    finally { setConnecting(false) }
  }

  async function forgetConnection() {
    try {
      const next = await api.forgetAgentProfile(provider)
      const option = next.providers.find(item => item.id === provider)
      if (option) loadProfile(option, next)
    } catch (error) { setError(error instanceof Error ? error.message : 'Could not forget this provider profile') }
  }

  async function resolve(proposal: AgentProposal, action: 'apply' | 'dismiss') {
    try {
      await api.resolveAgentProposal(proposal.id, action)
      setResult(current => current ? { ...current, proposals: current.proposals.map(item => item.id === proposal.id ? { ...item, status: action === 'apply' ? 'applied' : 'dismissed' } : item) } : current)
      if (action === 'apply') await onChanged()
    } catch (error) { setError(error instanceof Error ? error.message : 'Could not resolve that proposal') }
  }

  async function saveElaboration(action: 'update_original' | 'create_child') {
    if (!result || !contextIdea) return
    setSavingResult(action); setError('')
    try {
      const saved = await api.saveAgentResult(result.id, action)
      setSavedResult(saved)
      await onChanged()
    } catch (error) { setError(error instanceof Error ? error.message : 'Could not save the elaboration') }
    finally { setSavingResult(null) }
  }

  return <div className="modal-backdrop agent-backdrop" onMouseDown={event => event.target === event.currentTarget && onClose()}>
    <section className="agent-workspace">
      <header><div><p className="eyebrow">RESEARCH AGENT</p><h2><Sparkles size={25}/> Agent chat</h2></div><button className="icon-button" onClick={onClose} aria-label="Close agent chat"><X size={20}/></button></header>
      {!status ? <div className="agent-loading"><LoaderCircle className="spin" size={20}/> Checking provider…</div> : <>
        <nav className="agent-provider-tabs" aria-label="Agent providers">{status.providers.map(item => <button key={item.id} className={provider === item.id ? 'active' : ''} onClick={() => void chooseProvider(item.id)}><span>{item.label}</span><i className={item.configured ? 'ready' : ''}/></button>)}</nav>
        {(!status.configured || editingConnection) ? <div className="agent-setup agent-connection-form">
          <KeyRound size={22}/><div><strong>{activeProfile?.label} profile</strong><p>Each tab keeps its own endpoint, model, reasoning level, and credential. Switching tabs restores that provider automatically.</p>
            <label>API key {!activeProfile?.api_key_required && <span>optional</span>}<input type="password" autoComplete="new-password" value={apiKey} onChange={event => setApiKey(event.target.value)} placeholder={activeProfile?.credential_stored ? 'Saved securely — leave blank to keep it' : activeProfile?.api_key_required ? `${activeProfile.label} API key` : 'Bearer token, if your local server requires one'}/></label>
            <label>Model{activeProfile?.models.length ? <select value={connectionModel} onChange={event => setConnectionModel(event.target.value)}>{!activeProfile.models.includes(connectionModel) && <option value={connectionModel}>{connectionModel}</option>}{activeProfile.models.map(item => <option value={item} key={item}>{item}</option>)}</select> : <input value={connectionModel} onChange={event => setConnectionModel(event.target.value)} placeholder="Local model name"/>}</label>
            <label>Thinking effort<select value={connectionReasoningEffort} onChange={event => setConnectionReasoningEffort(event.target.value as ReasoningEffort)}>{activeProfile?.reasoning_efforts.map(item => <option value={item} key={item}>{item === 'none' ? 'None / fastest' : item}</option>)}</select></label>
            <label>Base URL<input value={baseUrl} onChange={event => setBaseUrl(event.target.value)} placeholder="https://provider.example/v1"/></label>
            <p className="agent-provider-note">IdeaMiner uses Anthropic Messages for Anthropic and an OpenAI-compatible Responses endpoint for the other tabs. A local server normally uses <code>http://127.0.0.1:11434/v1</code>.</p>
            <label className="agent-remember"><input type="checkbox" checked={rememberApiKey} disabled={!status.credential_store_available || !apiKey.trim() && !activeProfile?.credential_stored} onChange={event => setRememberApiKey(event.target.checked)}/> Remember this credential in the operating system vault</label>
            <div className="agent-connect-actions">{status.configured && <button className="button secondary small" onClick={() => setEditingConnection(false)}>Cancel</button>}<button className="button primary small" disabled={connecting || !keyReady || !connectionModel.trim() || !baseUrl.trim()} onClick={connect}>{connecting ? <LoaderCircle className="spin" size={15}/> : <KeyRound size={15}/>} Save profile</button></div>
            <small><ShieldCheck size={13}/> Keys are never stored in SQLite, browser storage, exports, or the profile file. {!status.credential_store_available && 'Secure OS storage is unavailable, so new keys remain session-only.'}</small>
          </div></div> : <div className="agent-connected"><ShieldCheck size={18}/><div><strong>{status.provider_label} ready</strong><span>{status.default_model} · {status.reasoning_effort} effort · {status.configuration_source === 'secure_storage' ? 'credential remembered' : status.configuration_source === 'session' ? 'session credential' : status.configuration_source === 'environment' ? 'environment credential' : 'local endpoint'}</span><small>{status.base_url}</small></div><button onClick={() => setEditingConnection(true)}>Edit</button><button onClick={() => void forgetConnection()}>Forget</button></div>}
        {status.configured && <>
        <div className="agent-session-bar">
          <label><span>Project context</span><select value={sessionScope.type === 'all' ? 'all' : `${sessionScope.type}:${sessionScope.id}`} onChange={event => {
            const value = event.target.value
            if (value === 'all') setSessionScope({ type: 'all' })
            else { const [type, id] = value.split(':'); setSessionScope({ type: type as 'project' | 'group', id: Number(id) }) }
            setSelectedFileIds([])
          }}>
            <option value="all">All active projects</option>
            {groups.map(group => <option value={`group:${group.id}`} key={`group-${group.id}`}>Group · {group.name}</option>)}
            {projects.filter(project => project.system_key !== 'recycle').map(project => <option value={`project:${project.id}`} key={`project-${project.id}`}>Project · {project.name}</option>)}
          </select></label>
          <div><strong>{contextName}</strong>{contextIdea && <small>Idea context: {contextIdea.title}</small>}</div>
        </div>
        <p className="agent-privacy-note">{status.privacy}</p>
        <div className="agent-modes" aria-label="Research mode">{modes.map(item => <button key={item.id} className={mode === item.id ? 'active' : ''} onClick={() => chooseMode(item.id)}>{item.label}</button>)}</div>
        {availableFiles.length > 0 && <details className="agent-files"><summary><Paperclip size={14}/> Include local files <span>{selectedFileIds.length ? `${selectedFileIds.length} selected` : 'none selected'}</span></summary><p>Only checked text files are sent to the provider for this run. Their stable ID and local path are included; binary files contribute metadata only.</p><div>{availableFiles.map(file => <label className={file.exists ? '' : 'missing'} key={file.id}><input type="checkbox" disabled={!file.exists} checked={selectedFileIds.includes(file.id)} onChange={event => setSelectedFileIds(current => event.target.checked ? [...current, file.id] : current.filter(id => id !== file.id))}/><FileText size={14}/><span>{file.display_name}<small title={file.absolute_path}>{file.absolute_path}</small><small>{file.storage_mode === 'managed' ? 'managed copy' : 'linked original'}{!file.exists && ' · missing'}</small></span></label>)}</div></details>}
        <section className="agent-chat-history" aria-live="polite">
          {chatMessages.length === 0 ? <div className="agent-chat-welcome"><Sparkles size={19}/><strong>{status.provider_label} is ready</strong><span>Ask a question or describe what you want to work on. The selected project context will be available throughout this chat.</span></div> : chatMessages.map((message, index) => <article className={`agent-chat-message ${message.role}`} key={`${index}-${message.role}`}>
            <span>{message.role === 'user' ? 'You' : status.provider_label}</span>
            <div className={message.role === 'assistant' ? 'markdown' : ''}>{message.role === 'assistant' ? <IdeaMarkdown content={message.content} ideas={ideas} attachments={availableFiles} onIdeaSelect={onIdeaSelect} onFileOpen={id => void api.openAttachment(id)}/> : message.content}</div>
          </article>)}
          {running && <div className="agent-chat-thinking"><LoaderCircle className="spin" size={16}/> Thinking…</div>}
          <div className="agent-chat-end" ref={chatEndRef}/>
        </section>
        <div className="agent-composer"><textarea className="agent-prompt" rows={3} value={prompt} onChange={event => setPrompt(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void run() } }} placeholder="Message your research agent… (Enter to send, Shift+Enter for a new line)"/><button className="button primary" disabled={running || !prompt.trim()} onClick={() => void run()}>{running ? <LoaderCircle className="spin" size={16}/> : <Send size={16}/>} Send</button></div>
        <div className="agent-options"><label title={status.web_search_supported ? `Use ${status.provider_label}'s server-side web search` : 'This provider preset does not advertise web search'}><input type="checkbox" checked={webSearch} disabled={!status.web_search_supported} onChange={event => setWebSearch(event.target.checked)}/><Globe2 size={15}/> Allow {status.provider_label} web search</label><label>Model {activeProfile?.models.length ? <select value={model} onChange={event => setModel(event.target.value)}>{!activeProfile.models.includes(model) && <option value={model}>{model}</option>}{activeProfile.models.map(item => <option value={item} key={item}>{item}</option>)}</select> : <input value={model} onChange={event => setModel(event.target.value)} />}</label><label>Thinking <select value={reasoningEffort} onChange={event => setReasoningEffort(event.target.value as ReasoningEffort)}>{activeProfile?.reasoning_efforts.map(item => <option value={item} key={item}>{item}</option>)}</select></label></div>
        </>}
      </>}
      {error && <div className="error-banner agent-error">{error}<button onClick={() => setError('')}><X size={15}/></button></div>}
      {result && <div className="agent-result">
        <div className="agent-result-meta"><span>{result.provider}</span><span>{result.model}</span><span>{result.context_summary.ideas} ideas · {result.context_summary.relations} relations · {result.context_summary.files} files</span><span>Raw captures not shared</span></div>
        {contextIdea && resultMode === 'elaborate' && <section className={`agent-save-result ${savedResult ? 'saved' : ''}`}>
          {savedResult ? <><Check size={18}/><div><strong>{savedResult.action === 'create_child' ? 'Saved as a descendant' : 'Original idea updated'}</strong><span>{savedResult.idea.title}</span></div></> : <><div><strong>Save this elaboration</strong><span>Update the current idea, or create a linked child while keeping the original unchanged.</span></div><aside><button className="button secondary small" disabled={savingResult !== null} onClick={() => saveElaboration('update_original')}>{savingResult === 'update_original' ? <LoaderCircle className="spin" size={14}/> : <Save size={14}/>} Update original</button><button className="button primary small" disabled={savingResult !== null} onClick={() => saveElaboration('create_child')}>{savingResult === 'create_child' ? <LoaderCircle className="spin" size={14}/> : <GitBranch size={14}/>} Save as descendant</button></aside></>}
        </section>}
        {result.proposals.length > 0 && <section className="agent-proposals"><h3>Suggested changes <span>Review before applying</span></h3>{result.proposals.map(proposal => <article key={proposal.id} className={`agent-proposal ${proposal.status}`}>
          <div><span>{proposal.action_type.replaceAll('_', ' ')}</span><strong>{proposal.title}</strong><p>{proposal.rationale}</p><small>{payloadPreview(proposal)}</small></div>
          {proposal.status === 'pending' ? <aside><button className="button secondary small" onClick={() => resolve(proposal, 'dismiss')}>Dismiss</button><button className="button primary small" onClick={() => resolve(proposal, 'apply')}><Check size={14}/> Apply</button></aside> : <em>{proposal.status === 'applied' ? 'Applied' : 'Dismissed'}</em>}
        </article>)}</section>}
      </div>}
    </section>
  </div>
}
