import * as React from 'react'
import * as Popover from '@radix-ui/react-popover'
import { Check, ChevronDown, Plus } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ScrollArea } from './scroll-area'

interface CreatableSelectProps {
  value: string
  options: string[]
  onChange: (v: string) => void
  placeholder?: string
  className?: string
}

export function CreatableSelect({
  value,
  options,
  onChange,
  placeholder,
  className
}: CreatableSelectProps) {
  const [open, setOpen] = React.useState(false)
  const [inputValue, setInputValue] = React.useState(value)
  React.useEffect(() => setInputValue(value), [value])

  const normalized = inputValue.trim()
  const filtered = React.useMemo(
    () => options.filter((o) => o.toLowerCase().includes(normalized.toLowerCase())),
    [options, normalized]
  )
  const canCreate = normalized && !options.some((o) => o === normalized)

  const select = (v: string) => {
    onChange(v)
    setInputValue(v)
    setOpen(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      if (normalized) {
        select(normalized)
      }
    }
  }

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button
          type="button"
          className={cn(
            'flex h-9 w-full items-center justify-between gap-2 rounded-md border border-input bg-card px-3 text-sm outline-none transition-shadow focus-within:ring-2 focus-within:ring-[var(--ring)] disabled:opacity-50 cursor-pointer',
            className
          )}
        >
          <input
            value={inputValue}
            onChange={(e) => {
              setInputValue(e.target.value)
              if (!open) setOpen(true)
            }}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-muted-foreground"
            onClick={(e) => {
              e.stopPropagation()
              setOpen(true)
            }}
          />
          <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-60" />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={6}
          className="z-50 w-[var(--radix-popover-trigger-width)] rounded-lg border border-border bg-card p-1 shadow-lg data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95"
        >
          <ScrollArea className="max-h-64">
            {filtered.length === 0 && !canCreate && (
              <div className="px-3 py-6 text-center text-xs text-muted-foreground">暂无候选，输入后回车新增</div>
            )}
            {filtered.map((opt) => (
              <button
                key={opt}
                type="button"
                onClick={() => select(opt)}
                className={cn(
                  'flex w-full cursor-pointer items-center justify-between rounded-md px-2.5 py-1.5 text-left text-sm hover:bg-muted',
                  opt === value && 'bg-muted'
                )}
              >
                <span className="truncate">{opt}</span>
                {opt === value && <Check className="h-3.5 w-3.5 shrink-0 text-accent" />}
              </button>
            ))}
            {canCreate && (
              <button
                type="button"
                onClick={() => select(normalized)}
                className="flex w-full cursor-pointer items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm text-accent hover:bg-muted"
              >
                <Plus className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">使用 "{normalized}"</span>
              </button>
            )}
          </ScrollArea>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
