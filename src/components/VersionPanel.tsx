import { useEffect, useState } from 'react'
import { Check, Download, ExternalLink, RefreshCw, Trash2, X } from 'lucide-react'
import { api, type UpdateCheck } from '../api'

export function VersionPanel() {
  const [current, setCurrent] = useState('…')
  const [canUpdate, setCanUpdate] = useState(false)
  const [open, setOpen] = useState(false)
  const [check, setCheck] = useState<UpdateCheck | null>(null)
  const [checking, setChecking] = useState(false)
  const [error, setError] = useState('')
  const [applying, setApplying] = useState(false)
  const [uninstallChoice, setUninstallChoice] = useState(false)
  const [uninstalling, setUninstalling] = useState(false)

  useEffect(() => { void api.updateVersion().then(value => { setCurrent(value.current_version); setCanUpdate(value.can_update) }).catch(() => setCurrent('unknown')) }, [])

  async function checkNow() {
    setChecking(true); setError('')
    try { const result = await api.checkUpdates(); setCheck(result); setCurrent(result.current_version); setCanUpdate(result.can_update) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not check for updates.') }
    finally { setChecking(false) }
  }

  function show() { setOpen(true); void checkNow() }
  async function install() {
    setApplying(true); setError('')
    try { await api.applyUpdate() }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not start the updater.'); setApplying(false) }
  }

  async function uninstall(keepDatabase: boolean) {
    setUninstalling(true); setError('')
    try { await api.uninstallApp(keepDatabase) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not start the uninstaller.'); setUninstalling(false) }
  }

  return <>
    <button className="version-trigger" onClick={show} title="Check IdeaMiner version and updates"><span>IdeaMiner</span><small>v{current}</small></button>
    {open && <div className="modal-backdrop version-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) setOpen(false) }}>
      <section className="editor version-dialog" role="dialog" aria-modal="true" aria-labelledby="version-title">
        <header><div><p className="eyebrow">APPLICATION</p><h2 id="version-title">Version and updates</h2></div><button className="icon-button" onClick={() => setOpen(false)} aria-label="Close"><X size={18}/></button></header>
        {!uninstallChoice ? <>
        <div className="version-current"><span>Installed version</span><strong>v{current}</strong></div>
        {checking && <p className="version-message"><RefreshCw size={15} className="version-spin"/> Checking the latest release…</p>}
        {!checking && check?.status === 'up_to_date' && <p className="version-message success"><Check size={16}/> You’re using the latest version.</p>}
        {!checking && check?.status === 'available' && <div className="version-available"><p>A newer version is available: <strong>v{check.latest_version}</strong></p>{check.published_at && <small>Released {new Date(check.published_at).toLocaleDateString()}</small>}</div>}
        {!checking && check?.status === 'unavailable' && <p className="version-message">Could not reach GitHub. Your installed version is still shown above.</p>}
        {check?.release_notes && <div className="version-notes"><h3>Release notes</h3><pre>{check.release_notes}</pre></div>}
        {error && <p className="error-message">{error}</p>}
        {applying && <p className="version-message">The updater is starting. IdeaMiner will close, install the update, then reopen.</p>}
        <footer>
          <button className="button secondary" onClick={() => void checkNow()} disabled={checking || applying}><RefreshCw size={14}/> Check again</button>
          {check?.update_available && check.can_update && <button className="button primary" onClick={() => void install()} disabled={applying}><Download size={15}/> Install and restart</button>}
          {check?.update_available && !check.can_update && <a className="button primary" href={check.release_url} target="_blank" rel="noreferrer"><ExternalLink size={15}/> View release</a>}
          {!check?.update_available && check?.release_url && <a className="version-release-link" href={check.release_url} target="_blank" rel="noreferrer">View releases <ExternalLink size={12}/></a>}
          {canUpdate && <button className="button version-uninstall-button" onClick={() => { setUninstallChoice(true); setError('') }} disabled={applying}><Trash2 size={14}/> Uninstall IdeaMiner</button>}
        </footer>
        </> : <div className="version-uninstall-options">
          <p className="eyebrow">REMOVE IDEAMINER</p><h3>What should be kept?</h3>
          {uninstalling ? <p className="version-message">The uninstaller is starting. IdeaMiner will close and remove the selected files.</p> : <>
            <button onClick={() => void uninstall(true)}><strong>Keep only the database</strong><span>Remove the app, settings, and other local IdeaMiner data. Keep the SQLite library database.</span></button>
            <button className="danger-option" onClick={() => void uninstall(false)}><strong>Remove everything</strong><span>Remove the app and all IdeaMiner data stored in its local data folder.</span></button>
            <p className="version-uninstall-note">Files in your project workspace folders are left untouched.</p>
            {error && <p className="error-message">{error}</p>}
            <footer><button className="button secondary" onClick={() => setUninstallChoice(false)}>Cancel</button></footer>
          </>}
        </div>}
      </section>
    </div>}
  </>
}
