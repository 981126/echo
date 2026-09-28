import { cn } from '@/lib/utils'

/**
 * R-198：筛选下拉的「默认（不筛选）」态灰字展示。
 *
 * 根因：Radix 的 SelectValue 会把选中项文字按正常前景色渲染，而「全部」项的文案原本
 * 就是字段名（如「广告」），看上去像已生效的筛选条件。这里让默认态回落成占位符观感，
 * 只有用户真的选了具体值才用正常前景色 + 具体值文案。
 */
export function FilterValue({ active, name, label }: { active: boolean; name: string; label?: string }) {
  return <span className={cn(!active && 'text-muted-foreground')}>{active ? (label ?? name) : name}</span>
}
