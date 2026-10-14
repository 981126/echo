import * as React from 'react'
import * as Popover from '@radix-ui/react-popover'
import { ChevronDown, Plus, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Checkbox } from './checkbox'
import { ScrollArea } from './scroll-area'

interface CreatableMultiSelectProps {
  options: string[]
  value: string[]
  onChange: (v: string[]) => void
  placeholder?: string
  className?: string
}

export function CreatableMultiSelect({
  options,
  value,
  onChange,
  placeholder,
  className
}: CreatableMultiSelectProps) {
  const [open, setOpen] = React.useState(false)
  const [inputValue, setInputValue] = React.useState('')
  const normalized = inputValue.trim()

  const filtered = React.useMemo(
    () => options.filter((o) => o.toLowerCase().includes(normalized.toLowerCase())),
    [options, normalized]
  )
  const canCreate = normalized && !options.some((o) => o === normalized)

  const toggle = (opt: string) => {
    onChange(value.includes(opt) ? value.filter((v) => v !== opt) : [...value, opt])
  }

  const addNew = (v: string) => {
    const s = v.trim()
    if (!s || value.includes(s)) return
    onChange([...value, s])
    setInputValue('')
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      if (normalized) {
        if (canCreate) {
          addNew(normalized)
        } else if (filtered.length === 1) {
          toggle(filtered[0])
        }
      }
    }
  }

  const clearAll = (e: React.MouseEvent) => {
    e.stopPropagation()
    onChange([])
  }

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button
          type="button"
          className={cn(
            'flex h-9 min-w-0 items-center justify-between gap-2 rounded-md border border-input bg-card px-3 text-sm outline-none transition-shadow focus-within:ring-2 focus-within:ring-[var(--ring)] cursor-pointer',
            className
          )}
        >
          <span className={cn('truncate', !value.length && 'text-muted-foreground')}>
            {value.length ? `${placeholder} · ${value.length}` : placeholder}
          </span>
          <span className="flex shrink-0 items-center gap-1">
            {value.length > 0 && (
              <X
                className="h-3.5 w-3.5 opacity-60 hover:opacity-100"
                onClick={clearAll}
              />
            )}
            <ChevronDown className="h-3.5 w-3.5 opacity-60" />
          </span>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={6}
          className="z-50 w-56 rounded-lg border border-border bg-card p-1 shadow-lg data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95"
        >
          <div className="px-2 pb-1 pt-1">
            <input
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入新标签…"
              className="h-7 w-full rounded bg-muted px-2 text-sm outline-none placeholder:text-muted-foreground"
              onClick={(e) => e.stopPropagation()}
            />
          </div>
          <ScrollArea className="max-h-64">
            {filtered.length === 0 && !canCreate && (
              <div className="px-3 py-6 text-center text-xs text-muted-foreground">暂无可选项</div>
            )}
            {filtered.map((opt) => (
              <label
                key={opt}
                className="flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm hover:bg-muted"
              >
                <Checkbox checked={value.includes(opt)} onCheckedChange={() => toggle(opt)} />
                <span className="truncate">{opt}</span>
              </label>
            ))}
            {canCreate && (
              <button
                type="button"
                onClick={() => addNew(normalized)}
                className="flex w-full cursor-pointer items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm text-accent hover:bg-muted"
              >
                <Plus className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">新增 "{normalized}"</span>
              </button>
            )}
          </ScrollArea>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
