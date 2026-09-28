import { useCallback, useEffect, useState } from 'react'
import { Beaker, ChevronDown, LoaderCircle, Plus, Search } from 'lucide-react'
import { api } from '../api'
import type { Attachment, ExperimentStatus, Idea, MicroExperiment } from '../types'

const statuses: ExperimentStatus[] = ['planned', 'running', 'completed', 'failed', 'inconclusive', 'needs_follow_up']

export function ExperimentPanel({ ideaId, ideas, attachments = [], onChanged }: { ideaId: number; ideas: Idea[]; attachments?: Attachment[]; onChanged: () => Promise<void> }) {
  const [items, setItems] = useState<MicroExperiment[]>([])
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('')
  const [tried, setTried] = useState('')
  const [result, setResult] = useState('')
  const [takeaway, setTakeaway] = useState('')
  const [status, setStatus] = useState<ExperimentStatus>('planned')
  const [dataset, setDataset] = useState('')
  const [metrics, setMetrics] = useState('')
  const [codeRef, setCodeRef] = useState('')
  const [attachmentIds, setAttachmentIds] = useState<number[]>([])
  const [ideaLinks, setIdeaLinks] = useState<{ idea_id: number; role: string }[]>([{ idea_id: ideaId, role: 'tests' }])
  const [linkDraft, setLinkDraft] = useState<{ idea_id: number; role: string }>({ idea_id: 0, role: 'supports' })
  const [customFields, setCustomFields] = useState<string[]>([])
  const [enabled, setEnabled] = useState(true)
  const [metadata, setMetadata] = useState<Record<string, unknown>>({})
  const [repeats, setRepeats] = useState<(MicroExperiment & { score: number; feedback_key: string })[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try { const params = new URLSearchParams({ idea_id: String(ideaId) }); if (query.trim()) params.set('q', query.trim()); if (filter) params.set('status', filter); setItems(await api.experiments(params)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not load experiments') }
  }, [ideaId, query, filter])
  useEffect(() => { void load() }, [load])
  useEffect(() => { setIdeaLinks([{ idea_id: ideaId, role: 'tests' }]) }, [ideaId])
  useEffect(() => { api.researchSettings().then(value => { setCustomFields(value.experiment_fields); setEnabled(value.experiments_enabled) }).catch(() => {}) }, [])
  useEffect(() => {
    if (tried.trim().length < 4) { setRepeats([]); return }
    const timer = window.setTimeout(() => { api.repeatMatches(tried, ideaId).then(setRepeats).catch(() => setRepeats([])) }, 350)
    return () => window.clearTimeout(timer)
  }, [tried, ideaId])

  async function save() {
    if (!tried.trim()) return
    try {
      setBusy(true); setError('')
      let parsed: Record<string, unknown> = {}
      if (metrics.trim()) { const value: unknown = JSON.parse(metrics); if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error('Metrics must be a JSON object'); parsed = value as Record<string, unknown> }
      await api.createExperiment({ what_tried: tried.trim(), result, takeaway, status, dataset_material: dataset, metrics: parsed, code_ref: codeRef, metadata, idea_links: ideaLinks, attachment_ids: attachmentIds })
      setTried(''); setResult(''); setTakeaway(''); setDataset(''); setMetrics(''); setCodeRef(''); setAttachmentIds([]); setRepeats([]); setMetadata({}); setIdeaLinks([{ idea_id: ideaId, role: 'tests' }])
      await Promise.all([load(), onChanged()])
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not save experiment') }
    finally { setBusy(false) }
  }
  async function advance(item: MicroExperiment, next: ExperimentStatus, nextTakeaway = item.takeaway) {
    try { await api.updateExperiment(item.id, { what_tried: item.what_tried, result: item.result, takeaway: nextTakeaway, status: next, dataset_material: item.dataset_material, metrics: item.metrics, code_ref: item.code_ref, metadata: item.metadata, idea_links: item.ideas.map(link => ({ idea_id: link.idea_id, role: link.role })), attachment_ids: item.attachments.map(file => file.id) }); await load(); await onChanged() }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not update experiment') }
  }
  async function dismissRepeat(item: MicroExperiment & { feedback_key: string }) {
    try { await api.insightFeedback({ concept: 'experiment-repeat', subject_key: item.feedback_key, action: 'dismissed' }); setRepeats(current => current.filter(match => match.id !== item.id)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not dismiss this match') }
  }
  if (!enabled) return null
  return <section className="experiment-panel">
    <div className="research-panel-head"><h3><Beaker size={16}/> Micro-experiments</h3><span>{items.length}</span></div>
    <div className="experiment-search"><Search size={14}/><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search method, dataset, result…"/><select value={filter} onChange={event => setFilter(event.target.value)}><option value="">All statuses</option>{statuses.map(value => <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>)}</select></div>
    {items.map(item => <article className="experiment-item" key={item.id}><div className="experiment-item-top"><strong>{item.what_tried}</strong><select value={item.status} onChange={event => void advance(item, event.target.value as ExperimentStatus)}>{statuses.map(value => <option key={value}>{value}</option>)}</select></div>{item.result && <p>{item.result}</p>}{item.takeaway && <small>Takeaway · {item.takeaway}</small>}{item.dataset_material && <small>Material · {item.dataset_material}</small>}{item.code_ref && <small>Code · {item.code_ref}</small>}{item.attachments.map(file => <button className="experiment-file-link" key={file.id} onClick={() => void api.openAttachment(file.id)}>{file.asset_role} · {file.display_name}</button>)}<details><summary>Complete or edit takeaway <ChevronDown size={13}/></summary><textarea defaultValue={item.takeaway} placeholder="What did you learn?" onBlur={event => { if (event.target.value !== item.takeaway) void advance(item, item.status, event.target.value) }}/><select value={item.status} onChange={event => void advance(item, event.target.value as ExperimentStatus)}>{statuses.map(value => <option key={value}>{value}</option>)}</select></details></article>)}
    {!items.length && <p className="empty-small">No experiments linked to this idea yet.</p>}
    <div className="experiment-editor"><strong>Log a quick experiment</strong><textarea value={tried} onChange={event => setTried(event.target.value)} placeholder="What did you try?" rows={2}/>
      {repeats.length > 0 && <div className="repeat-notice"><strong>Similar past work</strong>{repeats.slice(0,3).map(item => <div key={item.id}><button onClick={() => setQuery(item.what_tried)}>{item.status} · {item.what_tried}</button><button title="Dismiss this match" onClick={() => void dismissRepeat(item)}>×</button></div>)}</div>}
      <div className="experiment-quick-row"><select value={status} onChange={event => setStatus(event.target.value as ExperimentStatus)}>{statuses.map(value => <option key={value}>{value}</option>)}</select><input value={takeaway} onChange={event => setTakeaway(event.target.value)} placeholder="Takeaway (optional)"/><button className="button primary small" disabled={busy || !tried.trim()} onClick={() => void save()}>{busy ? <LoaderCircle size={14} className="spin"/> : 'Log'}</button></div>
      <details className="experiment-advanced"><summary>Result and metadata <ChevronDown size={13}/></summary><textarea value={result} onChange={event => setResult(event.target.value)} placeholder="Result"/><div className="experiment-quick-row"><input value={dataset} onChange={event => setDataset(event.target.value)} placeholder="Dataset or material"/><input value={codeRef} onChange={event => setCodeRef(event.target.value)} placeholder="Git commit or code reference"/></div><textarea value={metrics} onChange={event => setMetrics(event.target.value)} placeholder={'Metrics as JSON, e.g. {"accuracy": 0.91}'}/>{attachments.length>0 && <div className="experiment-attachments">{attachments.map(file => <label key={file.id}><input type="checkbox" checked={attachmentIds.includes(file.id)} onChange={event => setAttachmentIds(current => event.target.checked ? [...current,file.id] : current.filter(id => id!==file.id))}/>{file.display_name}</label>)}</div>}</details>
      <details className="experiment-advanced"><summary>Links and custom fields <ChevronDown size={13}/></summary><div className="experiment-link-list">{ideaLinks.map((link,index) => <div key={`${link.idea_id}-${link.role}-${index}`}><span>{ideas.find(item => item.id===link.idea_id)?.title ?? `Idea ${link.idea_id}`}</span><select value={link.role} onChange={event => setIdeaLinks(current => current.map((item,i) => i===index ? { ...item, role:event.target.value } : item))}>{['tests','supports','contradicts','motivated-by','follow-up'].map(role => <option key={role}>{role}</option>)}</select>{index>0 && <button className="icon-button" onClick={() => setIdeaLinks(current => current.filter((_,i) => i!==index))}>×</button>}</div>)}</div><div className="experiment-quick-row"><select value={linkDraft.idea_id} onChange={event => setLinkDraft(current => ({ ...current, idea_id:Number(event.target.value) }))}><option value={0}>Link another idea…</option>{ideas.filter(item => !ideaLinks.some(link => link.idea_id===item.id)).map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select><select value={linkDraft.role} onChange={event => setLinkDraft(current => ({ ...current, role:event.target.value }))}>{['tests','supports','contradicts','motivated-by','follow-up'].map(role => <option key={role}>{role}</option>)}</select><button className="button secondary small" disabled={!linkDraft.idea_id} onClick={() => { setIdeaLinks(current => [...current,linkDraft]); setLinkDraft({ idea_id:0, role:'supports' }) }}><Plus size={13}/> Add link</button></div>{customFields.map(field => <label className="experiment-custom-field" key={field}>{field}<input value={String(metadata[field] ?? '')} onChange={event => setMetadata(current => ({ ...current, [field]:event.target.value }))}/></label>)}</details>
    </div>{error && <p className="error-text">{error}</p>}
  </section>
}
