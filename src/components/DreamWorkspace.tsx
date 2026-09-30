import { useEffect, useMemo, useState } from 'react'
import { Check, CloudMoon, LoaderCircle, Sparkles, X } from 'lucide-react'
import { api } from '../api'
import { IdeaMarkdown } from './IdeaMarkdown'
import type { AgentProposal, AgentRunResult, AgentStatus, Idea, Project } from '../types'
import { useI18n } from '../i18n'

function proposalPreview(proposal: AgentProposal) {
  const tags = Array.isArray(proposal.payload.tags) ? proposal.payload.tags.join(', ') : 'dreams'
  return `${String(proposal.payload.status || 'seed')} · #${tags.replaceAll(', ', ' #')}`
}

export function DreamWorkspace({ ideaIds, ideas, projects, onClose, onRemove, onChanged, onIdeaSelect, onOpenAgent }: {
  ideaIds: number[]
  ideas: Idea[]
  projects: Project[]
  onClose: () => void
  onRemove: (id: number) => void
  onChanged: () => Promise<void>
  onIdeaSelect: (id: number) => void
  onOpenAgent: () => void
}) {
  const { t } = useI18n()
  const sources = useMemo(() => ideaIds.map(id => ideas.find(item => item.id === id)).filter((item): item is Idea => Boolean(item)), [ideaIds, ideas])
  const activeProjects = projects.filter(item => item.system_key !== 'recycle')
  const [destination, setDestination] = useState(activeProjects.find(item => item.system_key === 'random_chat')?.id ?? activeProjects[0]?.id ?? 0)
  const [prompt, setPrompt] = useState('')
  const [status, setStatus] = useState<AgentStatus | null>(null)
  const [model, setModel] = useState('')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<AgentRunResult | null>(null)

  useEffect(() => { api.agentStatus().then(value => { setStatus(value); setModel(value.default_model) }).catch(reason => setError(reason instanceof Error ? reason.message : 'Could not inspect agent setup')) }, [])

  async function dream() {
    if (sources.length < 2 || !destination) return
    setRunning(true); setError(''); setResult(null)
    try { setResult(await api.dream({ idea_ids: sources.map(item => item.id), prompt, project_id: destination, model })) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Dream could not be completed') }
    finally { setRunning(false) }
  }

  async function resolve(proposal: AgentProposal, action: 'apply' | 'dismiss') {
    try {
      await api.resolveAgentProposal(proposal.id, action)
      setResult(current => current ? { ...current, proposals: current.proposals.map(item => item.id === proposal.id ? { ...item, status: action === 'apply' ? 'applied' : 'dismissed' } : item) } : current)
      if (action === 'apply') await onChanged()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not update Dream proposal') }
  }

  return <div className="modal-backdrop dream-backdrop" onMouseDown={event => event.target === event.currentTarget && onClose()}><section className="dream-workspace">
    <header><div><p className="eyebrow">{t('IDEA DREAMING')}</p><h2><CloudMoon size={25}/> {t('Dream together')}</h2><p>{t('Combine ideas from anywhere in your library. Sources remain untouched until you choose to apply a proposal.')}</p></div><button className="icon-button" onClick={onClose} aria-label={t('Close Dream')}><X size={20}/></button></header>
    <section className="dream-sources"><div><strong>{t('Dream sources')}</strong><span>{t('Drag cards into the Dream dock, even from different projects.')}</span></div>{sources.length ? <div className="dream-source-list">{sources.map(item => <article key={item.id}><span className={`status-dot ${item.status}`}/><strong>{item.title}</strong><small>#{item.id}</small><button onClick={() => onRemove(item.id)} aria-label={`${t('Remove')} ${item.title}`}><X size={14}/></button></article>)}</div> : <p className="empty-small">{t('Add at least two cards to begin a Dream.')}</p>}</section>
    {status && !status.configured && <div className="dream-setup"><div><strong>{t('An Agent connection is needed to Dream.')}</strong><span>{t('Open the Agent workspace once to enter the provider, API key, model, and endpoint for this local session.')}</span></div><button className="button secondary small" onClick={onOpenAgent}>{t('Configure Agent')}</button></div>}
    <label className="dream-prompt">{t('Optional direction')}<textarea rows={4} value={prompt} onChange={event => setPrompt(event.target.value)} placeholder={t('For example: favor a computational model that unifies these ideas, or find an unexpected experimental bridge.')}/></label>
    <div className="dream-options"><label>{t('New ideas go to')}<select value={destination} onChange={event => setDestination(Number(event.target.value))}>{activeProjects.map(project => <option value={project.id} key={project.id}>{project.name}</option>)}</select></label><label>{t('Model')}<input value={model} onChange={event => setModel(event.target.value)} placeholder={t('Use configured model')}/></label></div>
    <button className="button primary dream-run" disabled={!status?.configured || sources.length < 2 || running} onClick={() => void dream()}>{running ? <><LoaderCircle className="spin" size={17}/> {t('Dreaming…')}</> : <><Sparkles size={17}/> {t('Dream')} {sources.length || ''} {t('ideas')}</>}</button>
    {sources.length < 2 && <p className="dream-hint">{t('Add one more card to start. Dreams combine two to eight sources.')}</p>}
    {error && <div className="error-banner">{error}<button onClick={() => setError('')}><X size={15}/></button></div>}
    {result && <section className="dream-result"><div className="dream-result-meta"><span>{result.provider}</span><span>{result.model}</span><span>{result.proposals.length} {t('proposals · all start with #dreams')}</span></div><div className="markdown"><IdeaMarkdown content={result.answer} ideas={ideas} onIdeaSelect={onIdeaSelect}/></div>{result.proposals.length ? <div className="dream-proposals">{result.proposals.map(proposal => <article className={`agent-proposal ${proposal.status}`} key={proposal.id}><div><span>{t('DREAM IDEA')}</span><strong>{proposal.title}</strong><p>{proposal.rationale}</p><small>{proposalPreview(proposal)}</small></div>{proposal.status === 'pending' ? <aside><button className="button secondary small" onClick={() => void resolve(proposal, 'dismiss')}>{t('Dismiss')}</button><button className="button primary small" onClick={() => void resolve(proposal, 'apply')}><Check size={14}/> {t('Apply')}</button></aside> : <em>{t(proposal.status === 'applied' ? 'Applied' : 'Dismissed')}</em>}</article>)}</div> : <p className="empty-small">{t('The provider returned no distinct Dream ideas. Adjust the direction and try again.')}</p>}</section>}
  </section></div>
}
