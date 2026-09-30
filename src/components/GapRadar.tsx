import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Check, Clock3, X } from 'lucide-react'
import { api } from '../api'
import type { ResearchGap } from '../types'
import { useI18n } from '../i18n'

const scopeParams = (scope: { type: 'all' } | { type: 'project'; id: number } | { type: 'group'; id: number }) => {
  const params = new URLSearchParams()
  if (scope.type === 'project') params.set('project_id', String(scope.id))
  if (scope.type === 'group') params.set('group_id', String(scope.id))
  return params
}
const actionLabel = (type: string, t: (english: string) => string) => t(({ 'promising-untested':'Log experiment', 'experiment-without-takeaway':'Complete experiment', 'experiment-without-follow-up':'Plan follow-up', 'stalled-branch':'Open lineage' } as Record<string, string>)[type] ?? 'Open idea')

export function GapRadar({ scope, onIdeaSelect, onLineageSelect }: { scope: { type: 'all' } | { type: 'project'; id: number } | { type: 'group'; id: number }; onIdeaSelect: (id: number) => void; onLineageSelect: (id: number) => void }) {
  const { t } = useI18n()
  const [gaps, setGaps] = useState<ResearchGap[]>([])
  const [error, setError] = useState('')
  const load = useCallback(() => api.researchGaps(scopeParams(scope)).then(setGaps).catch(reason => setError(reason instanceof Error ? reason.message : 'Could not load Research Gap Radar')), [scope])
  useEffect(() => { void load() }, [load])
  async function feedback(item: ResearchGap, action: 'resolved' | 'dismissed' | 'snoozed') {
    const snooze = new Date(); snooze.setDate(snooze.getDate()+7)
    try { await api.insightFeedback({ concept: 'research-gap', subject_key: item.id, action, ...(action === 'snoozed' ? { snooze_until: snooze.toISOString() } : {}) }); await load() }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not update gap') }
  }
  return <section className="review-section gap-radar"><div className="review-section-head"><h3><AlertTriangle size={16}/> {t('Research Gap Radar')}</h3><span className="review-count">{gaps.length}</span></div><p className="review-note">{t('Local signals in your own idea and experiment history. No literature gap claims or quality scores.')}</p>{error && <p className="error-text">{error}</p>}{gaps.length ? <div className="gap-list">{gaps.map(item => <article key={item.id}><div className="gap-copy"><strong>{item.title}</strong><p>{item.detail}</p></div><div className="gap-actions">{item.target.idea_id && <button className="button primary small" onClick={() => item.type === 'stalled-branch' ? onLineageSelect(item.target.idea_id!) : onIdeaSelect(item.target.idea_id!)}>{actionLabel(item.type, t)}</button>}<button className="icon-button" title={t('Snooze for a week')} aria-label={t('Snooze for a week')} onClick={() => void feedback(item,'snoozed')}><Clock3 size={15}/></button><button className="icon-button" title={t('Resolve')} aria-label={t('Resolve')} onClick={() => void feedback(item,'resolved')}><Check size={15}/></button><button className="icon-button" title={t('Dismiss')} aria-label={t('Dismiss')} onClick={() => void feedback(item,'dismissed')}><X size={15}/></button></div></article>)}</div> : !error && <p className="empty-small">{t('Nothing needs attention right now.')}</p>}</section>
}
