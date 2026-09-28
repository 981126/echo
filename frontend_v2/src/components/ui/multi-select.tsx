import * as Popover from '@radix-ui/react-popover'
import { ChevronDown, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Checkbox } from './checkbox'
import { ScrollArea } from './scroll-area'

// 轻量多选：Popover + Checkbox 列表（平台/标签筛选用）
export function MultiSelect({
  options,
  value,
  onChange,
  placeholder,
  className
}: {
  options: string[]
  value: string[]
  onChange: (v: string[]) => void
  placeholder?: string
  className?: string
}) {
  const toggle = (opt: string) => {
    onChange(value.includes(opt) ? value.filter((v) => v !== opt) : [...value, opt])
  }
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          className={cn(
            'flex h-9 min-w-0 items-center justify-between gap-2 rounded-md border border-input bg-card px-3 text-sm outline-none transition-shadow focus:ring-2 focus:ring-[var(--ring)] cursor-pointer',
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
                onClick={(e) => {
                  e.stopPropagation()
                  onChange([])
                }}
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
          className="z-50 w-56 rounded-lg border border-border bg-card p-1 shadow-lg data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95"
        >
          <ScrollArea className="max-h-64">
            {options.length === 0 ? (
              <div className="px-3 py-6 text-center text-xs text-muted-foreground">暂无可选项</div>
            ) : (
              options.map((opt) => (
                <label
                  key={opt}
                  className="flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm hover:bg-muted"
                >
                  <Checkbox checked={value.includes(opt)} onCheckedChange={() => toggle(opt)} />
                  <span className="truncate">{opt}</span>
                </label>
              ))
            )}
          </ScrollArea>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
