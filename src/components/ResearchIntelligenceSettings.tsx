import { useEffect, useState } from 'react'
import { BrainCircuit, Save } from 'lucide-react'
import { api } from '../api'
import type { ResearchIntelligenceSettings } from '../types'

export function ResearchIntelligenceSettings() {
  const [settings, setSettings] = useState<ResearchIntelligenceSettings | null>(null)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { api.researchSettings().then(setSettings).catch(reason => setError(reason instanceof Error ? reason.message : 'Could not load settings')) }, [])
  function toggle(key: 'experiments_enabled' | 'gap_radar_enabled' | 'serendipity_enabled' | 'cross_project' | 'evidence_checks') { if (settings) setSettings({ ...settings, [key]: !settings[key] }) }
  async function save() { if (!settings) return; try { setSettings(await api.updateResearchSettings(settings)); setSaved(true); window.setTimeout(() => setSaved(false), 1800) } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not save settings') } }
  if (!settings) return <section className="review-section intelligence-settings"><h3><BrainCircuit size={16}/> Research Intelligence</h3>{error || 'Loading preferences…'}</section>
  return <details className="review-section intelligence-settings"><summary><h3><BrainCircuit size={16}/> Research Intelligence</h3><span>Personalize</span></summary><div className="settings-toggle-grid">{([["experiments_enabled","Micro-experiment Memory"],["gap_radar_enabled","Research Gap Radar"],["serendipity_enabled","Serendipity"]] as const).map(([key,label]) => <label key={key}><input type="checkbox" checked={settings[key]} onChange={() => toggle(key)}/>{label}</label>)}</div><div className="intelligence-thresholds"><label>Stalled after <input type="number" min={7} max={365} value={settings.stalled_days} onChange={event => setSettings({ ...settings, stalled_days: Number(event.target.value) })}/> days</label><label>Serendipity suggestions <input type="number" min={1} max={10} value={settings.serendipity_limit} onChange={event => setSettings({ ...settings, serendipity_limit: Number(event.target.value) })}/></label><label><input type="checkbox" checked={settings.cross_project} onChange={() => toggle('cross_project')}/> Prefer cross-project bridges</label><label><input type="checkbox" checked={settings.evidence_checks} onChange={() => toggle('evidence_checks')}/> Check promising ideas for evidence</label><label>Custom experiment fields (comma separated)<input value={settings.experiment_fields.join(', ')} onChange={event => setSettings({ ...settings, experiment_fields:event.target.value.split(',').map(value => value.trim()).filter(Boolean).slice(0,30) })}/></label></div>{error && <p className="error-text">{error}</p>}<button className="button secondary small" onClick={() => void save()}><Save size={14}/>{saved ? 'Saved' : 'Save preferences'}</button></details>
}
