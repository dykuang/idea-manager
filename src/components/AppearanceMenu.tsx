import { useEffect, useRef, useState } from 'react'
import { Check, Monitor, Moon, Palette, Sun, X } from 'lucide-react'

export type UiMode = 'classic' | 'studio'
export type Appearance = 'light' | 'dark' | 'system'
export type Density = 'comfortable' | 'compact' | 'dense'

export function AppearanceMenu({
  uiMode, appearance, density, onUiMode, onAppearance, onDensity,
}: {
  uiMode: UiMode
  appearance: Appearance
  density: Density
  onUiMode: (value: UiMode) => void
  onAppearance: (value: Appearance) => void
  onDensity: (value: Density) => void
}) {
  const [open, setOpen] = useState(false)
  const panel = useRef<HTMLDivElement>(null)
  const choices: { value: Appearance; label: string; Icon: typeof Sun }[] = [
    { value: 'light', label: 'Light', Icon: Sun },
    { value: 'dark', label: 'Dark', Icon: Moon },
    { value: 'system', label: 'System', Icon: Monitor },
  ]

  useEffect(() => {
    if (!open) return
    const dismiss = (event: MouseEvent) => { if (!panel.current?.contains(event.target as Node)) setOpen(false) }
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') { event.stopPropagation(); setOpen(false) } }
    window.addEventListener('mousedown', dismiss)
    window.addEventListener('keydown', key, true)
    return () => { window.removeEventListener('mousedown', dismiss); window.removeEventListener('keydown', key, true) }
  }, [open])

  return <div className="appearance-menu" ref={panel}>
    <button className="icon-button appearance-trigger" aria-label="Appearance settings" aria-haspopup="dialog" aria-expanded={open} title="Appearance" onClick={() => setOpen(value => !value)}><Palette size={16}/></button>
    {open && <section className="appearance-popover" role="dialog" aria-label="Appearance settings">
      <header><strong>Appearance</strong><button aria-label="Close appearance settings" onClick={() => setOpen(false)}><X size={15}/></button></header>
      <fieldset><legend>Interface</legend><div className="appearance-segment">
        {(['classic', 'studio'] as UiMode[]).map(value => <button key={value} aria-pressed={uiMode === value} className={uiMode === value ? 'active' : ''} onClick={() => onUiMode(value)}>{value === uiMode && <Check size={13}/>} {value === 'classic' ? 'Classic' : 'Studio'}</button>)}
      </div></fieldset>
      {uiMode === 'studio' && <>
        <fieldset><legend>Appearance</legend><div className="appearance-segment">
          {choices.map(({ value, label, Icon }) => <button key={value} aria-pressed={appearance === value} className={appearance === value ? 'active' : ''} onClick={() => onAppearance(value)}><Icon size={13}/>{label}</button>)}
        </div></fieldset>
        <fieldset><legend>Density</legend><div className="appearance-segment">
          {(['comfortable', 'compact', 'dense'] as Density[]).map(value => <button key={value} aria-pressed={density === value} className={density === value ? 'active' : ''} onClick={() => onDensity(value)}>{value[0].toUpperCase() + value.slice(1)}</button>)}
        </div></fieldset>
      </>}
    </section>}
  </div>
}
