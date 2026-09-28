import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowRight, ClipboardCheck, CloudMoon, Download, FolderKanban, GitFork, LayoutGrid, List, Plus, Search, Settings2, Sparkles, Tags, X } from 'lucide-react'
import type { Idea } from '../types'

type PaletteAction = { id: string; label: string; hint: string; Icon: typeof Search; run: () => void }

export function CommandPalette({
  ideas, onClose, onOpenIdea, onCapture, onAction, onSwitchMode, onToggleAppearance, uiMode,
}: {
  ideas: Idea[]
  onClose: () => void
  onOpenIdea: (id: number) => void
  onCapture: () => void
  onAction: (action: string) => void
  onSwitchMode: () => void
  onToggleAppearance: () => void
  uiMode: 'classic' | 'studio'
}) {
  const input = useRef<HTMLInputElement>(null)
  const returnFocus = useRef<HTMLElement | null>(document.activeElement instanceof HTMLElement ? document.activeElement : null)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)

  useEffect(() => {
    input.current?.focus()
    return () => returnFocus.current?.focus()
  }, [])

  const actions = useMemo<PaletteAction[]>(() => [
    { id: 'capture', label: 'Capture a new idea', hint: 'Create', Icon: Plus, run: onCapture },
    { id: 'review', label: 'Open Review', hint: 'Workflow', Icon: ClipboardCheck, run: () => onAction('review') },
    { id: 'graph', label: 'Open Graph', hint: 'View', Icon: GitFork, run: () => onAction('graph') },
    { id: 'lineage', label: 'Open Lineage', hint: 'View', Icon: ArrowRight, run: () => onAction('lineage') },
    { id: 'agent', label: 'Open Agent', hint: 'Workflow', Icon: Sparkles, run: () => onAction('agent') },
    { id: 'dream', label: 'Open Dream', hint: 'Workflow', Icon: CloudMoon, run: () => onAction('dream') },
    { id: 'projects', label: 'Manage projects', hint: 'Library', Icon: FolderKanban, run: () => onAction('projects') },
    { id: 'tags', label: 'Manage tags', hint: 'Library', Icon: Tags, run: () => onAction('tags') },
    { id: 'import', label: 'Import JSON', hint: 'Library', Icon: Download, run: () => onAction('import') },
    { id: 'export-json', label: 'Export JSON', hint: 'Library', Icon: Download, run: () => onAction('export-json') },
    { id: 'export-md', label: 'Export Markdown', hint: 'Library', Icon: Download, run: () => onAction('export-md') },
    { id: 'switch-mode', label: `Switch to ${uiMode === 'studio' ? 'Classic' : 'Studio'} design`, hint: 'Appearance', Icon: LayoutGrid, run: onSwitchMode },
    { id: 'toggle-appearance', label: 'Toggle dark appearance', hint: 'Appearance', Icon: Settings2, run: onToggleAppearance },
    { id: 'focus', label: 'Show Focus view', hint: 'View', Icon: List, run: () => onAction('focus') },
    { id: 'cards', label: 'Show Cards view', hint: 'View', Icon: LayoutGrid, run: () => onAction('cards') },
  ], [onAction, onCapture, onSwitchMode, onToggleAppearance, uiMode])

  const normalized = query.trim().toLocaleLowerCase()
  const ideaResults = normalized ? ideas.filter(idea =>
    idea.title.toLocaleLowerCase().includes(normalized) || idea.content.toLocaleLowerCase().includes(normalized) || idea.tags.some(tag => tag.toLocaleLowerCase().includes(normalized)),
  ).slice(0, 8) : []
  const actionResults = (normalized ? actions.filter(action => `${action.label} ${action.hint}`.toLocaleLowerCase().includes(normalized)) : actions.slice(0, 8)).slice(0, 8)
  const entries = [
    ...ideaResults.map(idea => ({ id: `idea-${idea.id}`, run: () => onOpenIdea(idea.id) })),
    ...actionResults.map(action => ({ id: action.id, run: action.run })),
  ]
  useEffect(() => { setActive(0) }, [query])

  function execute(index = active) {
    if (!entries.length) return
    onClose()
    entries[index]?.run()
  }

  return <div className="command-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
    <section className="command-palette" role="dialog" aria-modal="true" aria-label="Search ideas and commands">
      <label className="command-search"><Search size={18}/><input ref={input} value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => {
        if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); onClose() }
        else if (event.key === 'ArrowDown') { event.preventDefault(); setActive(index => Math.min(entries.length - 1, index + 1)) }
        else if (event.key === 'ArrowUp') { event.preventDefault(); setActive(index => Math.max(0, index - 1)) }
        else if (event.key === 'Enter') { event.preventDefault(); execute() }
      }} placeholder="Search ideas or commands…" aria-controls="command-results" aria-activedescendant={entries[active] ? `command-${entries[active].id}` : undefined}/><kbd>ESC</kbd><button aria-label="Close command palette" onClick={onClose}><X size={16}/></button></label>
      <div className="command-results" id="command-results" role="listbox" aria-label="Search results">
        {ideaResults.length > 0 && <div className="command-section-label">IDEAS</div>}
        {ideaResults.map((idea, index) => <button id={`command-idea-${idea.id}`} role="option" aria-selected={active === index} className={active === index ? 'active' : ''} key={idea.id} onMouseEnter={() => setActive(index)} onClick={() => execute(index)}><span className={`status-dot ${idea.status}`}/><span className="command-result-copy"><strong>{idea.title}</strong><small>{idea.tags.slice(0, 3).map(tag => `#${tag}`).join(' · ')}</small></span><span className="command-result-hint">Idea</span></button>)}
        {actionResults.length > 0 && <div className="command-section-label">{normalized ? 'COMMANDS' : 'QUICK ACTIONS'}</div>}
        {actionResults.map((action, index) => { const itemIndex = ideaResults.length + index; return <button id={`command-${action.id}`} role="option" aria-selected={active === itemIndex} className={active === itemIndex ? 'active' : ''} key={action.id} onMouseEnter={() => setActive(itemIndex)} onClick={() => execute(itemIndex)}><action.Icon size={15}/><span className="command-result-copy"><strong>{action.label}</strong></span><span className="command-result-hint">{action.hint}</span></button> })}
        {!entries.length && <p className="command-no-results">No matching ideas or commands.</p>}
      </div>
      <footer><span><kbd>↑</kbd><kbd>↓</kbd> Navigate</span><span><kbd>↵</kbd> Open</span><span>Search in this library</span></footer>
    </section>
  </div>
}
