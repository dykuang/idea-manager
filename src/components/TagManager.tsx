import { useEffect, useMemo, useState } from 'react'
import { Eye, EyeOff, List, Merge, Network, Search, Tags, X } from 'lucide-react'
import { api } from '../api'
import { tagStyle } from '../tagColors'
import type { TagInfo } from '../types'
import { TagMap } from './TagMap'
import { useI18n } from '../i18n'

type ManagedTag = TagInfo & { is_hidden: boolean }

type Scope = { type: 'all' } | { type: 'project'; id: number } | { type: 'group'; id: number }

export function TagManager({ visibleIdeaIds, scope, onClose, onChanged, onFilterTag }: { visibleIdeaIds: number[]; scope: Scope; onClose: () => void; onChanged: () => Promise<void>; onFilterTag: (name: string) => void }) {
  const { t } = useI18n()
  const [tags, setTags] = useState<ManagedTag[]>([])
  const [search, setSearch] = useState('')
  const [bulkAdd, setBulkAdd] = useState('')
  const [bulkRemove, setBulkRemove] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [view, setView] = useState<'list' | 'map'>('list')
  const [mapRevision, setMapRevision] = useState(0)

  async function load() {
    try { setTags(await api.managedTags()) } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not load tags') }
  }
  useEffect(() => { void load() }, [])
  const filtered = useMemo(() => tags.filter(tag => tag.name.includes(search.trim().toLowerCase()) || tag.group_name.toLowerCase().includes(search.trim().toLowerCase())), [tags, search])
  const split = (value: string) => value.split(',').map(item => item.trim()).filter(Boolean)

  async function refreshAfter(action: () => Promise<unknown>) {
    try { await action(); await Promise.all([load(), onChanged()]); setMapRevision(value => value + 1) } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not update tags') }
  }
  async function rename(tag: ManagedTag) {
    const value = window.prompt(`Rename #${tag.name} to:`, tag.name)?.trim().toLowerCase()
    if (!value || value === tag.name) return
    setBusy(tag.name); await refreshAfter(() => api.renameTag(tag.name, value)); setBusy(null)
  }
  async function merge(tag: ManagedTag) {
    const value = window.prompt(`Merge #${tag.name} into which existing tag?`)?.trim().toLowerCase()
    if (!value || value === tag.name) return
    setBusy(tag.name); await refreshAfter(() => api.mergeTag(tag.name, value)); setBusy(null)
  }
  async function saveSettings(tag: ManagedTag, changes: Partial<ManagedTag>) {
    const next = { ...tag, ...changes }
    setBusy(tag.name); await refreshAfter(() => api.updateTagSettings(tag.name, { group_name: next.group_name, is_hidden: next.is_hidden })); setBusy(null)
  }
  async function bulk() {
    if (!visibleIdeaIds.length || (!bulkAdd.trim() && !bulkRemove.trim())) return
    setBusy('bulk'); await refreshAfter(() => api.bulkUpdateTags({ idea_ids: visibleIdeaIds, add_tags: split(bulkAdd), remove_tags: split(bulkRemove) })); setBulkAdd(''); setBulkRemove(''); setBusy(null)
  }

  return <div className="modal-backdrop tag-manager-backdrop" onMouseDown={event => event.target === event.currentTarget && onClose()}><section className="modal tag-manager">
    <header><div><p className="eyebrow">{t('TAG MANAGER')}</p><h2><Tags size={22}/> {t('Keep your vocabulary useful')}</h2><p>{t('Group, hide, rename, or merge tags without losing their idea connections.')}</p></div><button className="icon-button" aria-label={t('Close')} onClick={onClose}><X size={20}/></button></header>
    {error && <div className="error-banner">{error}<button onClick={() => setError('')}><X size={14}/></button></div>}
    <div className="tag-manager-tools"><div className="tag-manager-view-toggle"><button className={view === 'list' ? 'active' : ''} onClick={() => setView('list')}><List size={14}/> {t('List')}</button><button className={view === 'map' ? 'active' : ''} onClick={() => setView('map')}><Network size={14}/> {t('Tag map')}</button></div>{view === 'list' && <label><Search size={15}/><input value={search} onChange={event => setSearch(event.target.value)} placeholder={t('Find a tag or group')}/></label>}<span>{tags.length} {t('tags · ')}{tags.filter(tag => tag.is_hidden).length} {t('hidden')}</span></div>
    <section className="tag-bulk"><div><strong>{t('Bulk update visible ideas')}</strong><span>{visibleIdeaIds.length} {t(visibleIdeaIds.length === 1 ? 'current idea selected by the current filters' : 'current ideas selected by the current filters')}</span></div><input value={bulkAdd} onChange={event => setBulkAdd(event.target.value)} placeholder={t('Add tags: method, review')}/><input value={bulkRemove} onChange={event => setBulkRemove(event.target.value)} placeholder={t('Remove tags: draft, old')}/><button className="button primary small" disabled={busy === 'bulk' || !visibleIdeaIds.length || (!bulkAdd.trim() && !bulkRemove.trim())} onClick={() => void bulk()}>{t('Apply')}</button></section>
    {view === 'map' ? <TagMap scope={scope} reloadToken={mapRevision} onFilterTag={onFilterTag}/> : <div className="tag-manager-list">{filtered.map(tag => <article key={tag.name} className={tag.is_hidden ? 'hidden-tag' : ''} style={tagStyle(tag.name, tag.group_name)}><div className="tag-manager-name"><strong><i/>#{tag.name}</strong><small>{tag.count} {t(tag.count === 1 ? 'active idea' : 'active ideas')}</small></div><label className="tag-group-input">{t('Group')}<input value={tag.group_name} placeholder={t('General')} onChange={event => setTags(current => current.map(item => item.name === tag.name ? { ...item, group_name: event.target.value } : item))} onBlur={() => void saveSettings(tag, { group_name: tags.find(item => item.name === tag.name)?.group_name ?? '' })}/></label><button title={t(tag.is_hidden ? 'Show in sidebar' : 'Hide from sidebar')} aria-label={t(tag.is_hidden ? 'Show in sidebar' : 'Hide from sidebar')} disabled={busy === tag.name} onClick={() => void saveSettings(tag, { is_hidden: !tag.is_hidden })}>{tag.is_hidden ? <EyeOff size={15}/> : <Eye size={15}/>}</button><button title={t('Rename tag')} disabled={busy === tag.name} onClick={() => void rename(tag)}>{t('Rename')}</button><button title={t('Merge into another tag')} disabled={busy === tag.name} onClick={() => void merge(tag)}><Merge size={14}/> {t('Merge')}</button></article>)}</div>}
  </section></div>
}
