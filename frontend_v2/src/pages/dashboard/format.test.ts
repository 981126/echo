import { describe, expect, it } from 'vitest'
import {
  deltaToneClass,
  formatCount,
  formatDateTime,
  formatDelta,
  formatHeat,
  formatMonthDay,
  formatMonthDayTime,
  formatPercent,
  formatRankPercent,
  formatUnitValue,
  statusTone
} from './format'

describe('数据看板格式化：万/亿与缺失值', () => {
  it('大数字按万/亿收敛，0 与缺失严格区分', () => {
    expect(formatCount(null)).toBe('暂无数据')
    expect(formatCount(undefined)).toBe('暂无数据')
    expect(formatCount(0)).toBe('0')
    expect(formatCount(999)).toBe('999')
    expect(formatCount(1234)).toBe('1,234')
    expect(formatCount(10_000)).toBe('1.00万')
    expect(formatCount(88_474)).toBe('8.85万')
    expect(formatCount(6_642_434)).toBe('664.2万')
    expect(formatCount(100_000_000)).toBe('1.0亿')
    expect(formatCount(-63)).toBe('-63')
    expect(formatCount(-63_000)).toBe('-6.30万')
  })

  it('热度同样走万/亿口径', () => {
    expect(formatHeat(null)).toBe('暂无数据')
    expect(formatHeat(0)).toBe('0')
    expect(formatHeat(20_382_486)).toBe('2038.2万')
    expect(formatHeat(230_000_000)).toBe('2.3亿')
  })
})

describe('数据看板格式化：百分比/排名/增减', () => {
  it('比率转百分比，0 是 0.0% 而不是暂无数据', () => {
    expect(formatPercent(null)).toBe('暂无数据')
    expect(formatPercent(0)).toBe('0.0%')
    expect(formatPercent(0.075246)).toBe('7.5%')
    expect(formatPercent(1)).toBe('100.0%')
    expect(formatPercent(0.6604, 0)).toBe('66%')
  })

  it('同类排名分位缺失显示 —', () => {
    expect(formatRankPercent(0.6604)).toBe('66%')
    expect(formatRankPercent(0)).toBe('0%')
    expect(formatRankPercent(null)).toBe('—')
  })

  it('较前 7 日增减带符号，无对比数据给出文案', () => {
    expect(formatDelta(null)).toBe('暂无对比（历史数据不足）')
    expect(formatDelta(0)).toBe('0')
    expect(formatDelta(12)).toBe('+12')
    expect(formatDelta(-63)).toBe('-63')
    expect(formatDelta(12_000)).toBe('+1.20万')
    expect(deltaToneClass(12)).toBe('text-success')
    expect(deltaToneClass(-1)).toBe('text-destructive')
    expect(deltaToneClass(0)).toBe('text-muted-foreground')
    expect(deltaToneClass(null)).toBe('text-muted-foreground')
  })
})

describe('数据看板格式化：时间与状态', () => {
  it('北京时间 naive ISO 直接截取，不做时区换算', () => {
    expect(formatDateTime('2026-11-01T06:50:36.473059')).toBe('2026-11-01 06:50')
    expect(formatDateTime('2026-11-01 06:50:36')).toBe('2026-11-01 06:50')
    expect(formatDateTime(null)).toBe('暂无数据')
    expect(formatDateTime('not-a-date')).toBe('暂无数据')
    expect(formatMonthDayTime('2026-10-29T21:45:05')).toBe('10-29 21:45')
    expect(formatMonthDayTime(null)).toBe('未记录')
    expect(formatMonthDay('2026-10-30')).toBe('10-30')
  })

  it('作品状态映射到徽标色调', () => {
    expect(statusTone('approved')).toBe('success')
    expect(statusTone('private')).toBe('secondary')
    expect(statusTone('rejected')).toBe('destructive')
    expect(statusTone('published')).toBe('default')
    expect(statusTone('unknown')).toBe('secondary')
    expect(statusTone('')).toBe('secondary')
  })

  it('单位格式化：ratio/秒/中文单位', () => {
    expect(formatUnitValue(0.305, 'ratio')).toBe('30.5%')
    expect(formatUnitValue(16.4, '秒')).toBe('16.4秒')
    expect(formatUnitValue(11_887, '次')).toBe('1.19万次')
    expect(formatUnitValue(0, '人')).toBe('0人')
    expect(formatUnitValue(null, '人')).toBe('暂无数据')
  })
})
