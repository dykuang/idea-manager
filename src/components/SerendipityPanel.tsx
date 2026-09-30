import { useCallback, useEffect, useState } from 'react'
import { ArrowLeftRight, CloudMoon, Eye, Link2, Save, Sparkles, X } from 'lucide-react'
import { api } from '../api'
import type { SerendipityPair } from '../types'
import { useI18n } from '../i18n'

export function SerendipityPanel({ onIdeaSelect, onDream, onChanged }: { onIdeaSelect: (id: number) => void; onDream: (ids: number[]) => void; onChanged: () => Promise<void> }) {
  const { t } = useI18n()
  const [items, setItems] = useState<SerendipityPair[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const load = useCallback(() => api.serendipity().then(setItems).catch(reason => setError(reason instanceof Error ? reason.message : 'Could not load Serendipity')), [])
  useEffect(() => { void load() }, [load])
  async function decide(item: SerendipityPair, action: 'saved' | 'dismissed') {
    try { setBusy(item.feedback_key); await api.insightFeedback({ concept: 'serendipity', subject_key: item.feedback_key, action }); await load() }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not save this suggestion') }
    finally { setBusy(null) }
  }
  async function connect(item: SerendipityPair) {
    try { setBusy(item.feedback_key); await api.createRelation({ source_id: item.source_id, target_id: item.target_id, relation_type: 'related-to', note: 'Connected from Serendipity' }); await api.insightFeedback({ concept: 'serendipity', subject_key: item.feedback_key, action: 'accepted' }); await load(); await onChanged() }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not connect these ideas') }
    finally { setBusy(null) }
  }
  return <section className="review-section serendipity-panel"><div className="review-section-head"><h3><Sparkles size={16}/> Serendipity</h3><span className="review-count">{items.length}</span></div><p className="review-note">{t('A few less-obvious bridges across methods, projects, and lineages. Different from nearest-neighbor suggestions.')}</p>{error && <p className="error-text">{error}</p>}{items.length ? <div className="serendipity-list">{items.map(item => <article key={item.feedback_key}><div className="serendipity-pair"><div><small>{item.source_project}</small><strong>{item.source_title}</strong></div><ArrowLeftRight size={17}/><div><small>{item.target_project}</small><strong>{item.target_title}</strong></div></div><p>{item.reason}</p><div className="serendipity-actions"><button className="button secondary small" onClick={() => onIdeaSelect(item.source_id)}><Eye size={14}/> {t('Inspect A')}</button><button className="button secondary small" onClick={() => onIdeaSelect(item.target_id)}><Eye size={14}/> {t('Inspect B')}</button><button className="button secondary small" onClick={() => onDream([item.source_id,item.target_id])}><CloudMoon size={14}/> {t('Dream together')}</button><button className="button secondary small" disabled={busy===item.feedback_key} onClick={() => void connect(item)}><Link2 size={14}/> {t('Connect')}</button><button className="icon-button" title={t('Save')} aria-label={t('Save')} onClick={() => void decide(item,'saved')}><Save size={15}/></button><button className="icon-button" title={t('Dismiss')} aria-label={t('Dismiss')} onClick={() => void decide(item,'dismissed')}><X size={15}/></button></div></article>)}</div> : !error && <p className="empty-small">{t('Nothing compelling this week.')}</p>}</section>
}
