import { useCallback, useEffect, useState } from 'react'
import { Beaker, Check, Clock3, Link2Off, RefreshCw, Sparkles, X } from 'lucide-react'
import { api } from '../api'
import type { Idea, MicroExperiment, ReviewData, SemanticStatus } from '../types'
import { GapRadar } from './GapRadar'
import { ResearchIntelligenceSettings } from './ResearchIntelligenceSettings'
import { SerendipityPanel } from './SerendipityPanel'
import { useI18n } from '../i18n'

type Scope = { type: 'all' } | { type: 'project'; id: number } | { type: 'group'; id: number }

function dateLabel(value: string) {
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(new Date(value))
}

export function ReviewDashboard({ scope, scopeTitle, onClose, onIdeaSelect, onLineageSelect, onChanged, onDream }: {
  scope: Scope
  scopeTitle: string
  onClose: () => void
  onIdeaSelect: (id: number) => void
  onLineageSelect: (id: number) => void
  onChanged: () => Promise<void>
  onDream: (ids: number[]) => void
}) {
  const { t } = useI18n()
  const [review, setReview] = useState<ReviewData | null>(null)
  const [semantic, setSemantic] = useState<SemanticStatus | null>(null)
  const [busy, setBusy] = useState<number | 'index' | null>(null)
  const [error, setError] = useState('')
  const [experimentReview, setExperimentReview] = useState<{ recently_completed: MicroExperiment[]; inconclusive: MicroExperiment[]; failed: MicroExperiment[]; untouched_planned: MicroExperiment[] } | null>(null)
  const params = new URLSearchParams()
  if (scope.type === 'project') params.set('project_id', String(scope.id))
  if (scope.type === 'group') params.set('group_id', String(scope.id))

  const load = useCallback(async () => {
    try {
      setError('')
      const [next, map, experiments] = await Promise.all([api.review(params), api.semanticStatus(), api.experimentReview(params)])
      setReview(next); setSemantic(map); setExperimentReview(experiments)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not load review') }
  // URLSearchParams is intentionally recreated from the selected stable scope.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope.type, scope.type === 'all' ? 0 : scope.id])

  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 5000); return () => window.clearInterval(timer) }, [load])

  async function resolve(id: number, action: 'apply' | 'dismiss') {
    try { setBusy(id); await api.resolveAgentProposal(id, action); await Promise.all([load(), onChanged()]) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not update proposal') }
    finally { setBusy(null) }
  }

  async function rebuild() {
    try { setBusy('index'); await api.rebuildSemantic(); await load() }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not build semantic map') }
    finally { setBusy(null) }
  }

  const ideaList = (items: Idea[], empty: string) => items.length ? <div className="review-idea-list">{items.map(item => <button key={item.id} onClick={() => onIdeaSelect(item.id)}><span><strong>{item.title}</strong><small>{t(item.status)} · {dateLabel(item.updated_at)}</small></span><span>{t('Open')}</span></button>)}</div> : <p className="empty-small">{t(empty)}</p>
  const stats = review?.summary
  const experimentRows = [...new Map([...(experimentReview?.recently_completed ?? []), ...(experimentReview?.inconclusive ?? []), ...(experimentReview?.failed ?? []), ...(experimentReview?.untouched_planned ?? [])].map(item => [item.id,item])).values()]
  return <div className="modal-backdrop review-backdrop" onMouseDown={event => event.target === event.currentTarget && onClose()}><section className="modal review-dashboard">
    <header className="review-header"><div><p className="eyebrow">{t('WEEKLY REVIEW')}</p><h2>{scopeTitle}</h2><p>{t('One place to reconnect, develop, and deliberately accept new work.')}</p></div><button className="icon-button" onClick={onClose} aria-label={t('Close weekly review')}><X size={20}/></button></header>
    {error && <div className="error-banner">{error}<button onClick={() => setError('')}><X size={14}/></button></div>}
    {!review ? <div className="loading"><RefreshCw/> {t('Loading review…')}</div> : <>
      <div className="review-stats"><div><strong>{stats?.active_ideas}</strong><span>{t('active ideas')}</span></div><div><strong>{stats?.new_captures}</strong><span>{t('new this week')}</span></div><div><strong>{stats?.unlinked}</strong><span>{t('unlinked')}</span></div><div><strong>{stats?.stale_seeds}</strong><span>{t('stale seeds')}</span></div><div><strong>{stats?.pending_proposals}</strong><span>{t('to review')}</span></div></div>
      <div className="review-columns"><section><h3><Clock3 size={16}/> {t('New captures')}</h3>{ideaList(review.new_captures, 'Nothing captured in the last seven days.')}</section><section><h3><Link2Off size={16}/> {t('Unlinked ideas')}</h3>{ideaList(review.unlinked, 'Every idea in this scope has a connection.')}</section></div>
      <section className="review-section"><h3><Clock3 size={16}/> {t('Seeds waiting for attention')}</h3>{ideaList(review.stale_seeds, 'No seed has been untouched for two weeks.')}</section>
      <section className="review-section"><h3><Beaker size={16}/> {t('Micro-experiments')}</h3>{experimentRows.length ? <div className="experiment-review-list">{experimentRows.slice(0,12).map(item => <article key={item.id}><div><strong>{item.what_tried}</strong><small>{t(item.status.replaceAll('_',' '))}{item.ideas?.[0] ? ` · ${item.ideas[0].title}` : ''}</small></div>{item.ideas?.[0] && <button className="button secondary small" onClick={() => onIdeaSelect(item.ideas[0].idea_id)}>{t('Open idea')}</button>}</article>)}</div> : <p className="empty-small">{t('No recent results or untouched plans.')}</p>}</section>
      <GapRadar scope={scope} onIdeaSelect={onIdeaSelect} onLineageSelect={onLineageSelect}/>
      <section className="review-section"><div className="review-section-head"><h3><Sparkles size={16}/> {t('Similar but unlinked')}</h3><button className="button secondary small" disabled={busy === 'index'} onClick={() => void rebuild()}><RefreshCw size={14} className={busy === 'index' ? 'spin' : ''}/>{t(semantic?.ready ? 'Rebuild local map' : 'Build local map')}</button></div><p className="review-note">{semantic?.ready ? <>{semantic.indexed_ideas} {t('active ideas indexed locally. Working titles and notes only; raw captures never leave SQLite.')}</> : t('Build a private local map to surface related ideas with no direct graph edge.')}</p>{review.semantic_opportunities.length ? <div className="semantic-list">{review.semantic_opportunities.map(item => <div key={`${item.source_id}-${item.target_id}`}><button onClick={() => onIdeaSelect(item.source_id)}>{item.source_title}</button><span>{Math.round(item.score * 100)}% {t('similar')}</span><button onClick={() => onIdeaSelect(item.target_id)}>{item.target_title}</button></div>)}</div> : semantic?.ready ? <p className="empty-small">{t('No strong unlinked pairs yet.')}</p> : null}</section>
      <section className="review-section"><h3><Check size={16}/> {t('Pending proposals')}</h3>{review.pending_proposals.length ? <div className="proposal-review-list">{review.pending_proposals.map(item => <article key={item.id}><div><small>{item.provider === 'codex' ? 'CODEX CHECKPOINT' : `${item.provider} · ${item.model}`}</small><strong>{item.title}</strong><p>{item.rationale || t('Review this proposed change before applying it.')}</p></div><div className="proposal-actions"><button className="button secondary small" disabled={busy === item.id} onClick={() => void resolve(item.id, 'dismiss')}>{t('Dismiss')}</button><button className="button primary small" disabled={busy === item.id} onClick={() => void resolve(item.id, 'apply')}>{t('Apply')}</button></div></article>)}</div> : <p className="empty-small">{t('No queued proposals. Agent and Codex checkpoint suggestions appear here for review.')}</p>}</section>
      <SerendipityPanel onIdeaSelect={onIdeaSelect} onDream={onDream} onChanged={onChanged}/>
      <ResearchIntelligenceSettings/>
    </>}
  </section></div>
}
