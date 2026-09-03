// 简易行级 diff（候选 vs 当前启用版），用于提示词启用前对比
export function diffLines(a, b) {
  const oldLines = (a || '').split('\n')
  const newLines = (b || '').split('\n')
  const n = oldLines.length
  const m = newLines.length
  const dp = Array.from({ length: n + 1 }, () => Array(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = oldLines[i] === newLines[j]
        ? dp[i + 1][j + 1] + 1
        : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  const out = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (oldLines[i] === newLines[j]) {
      out.push({ type: 'same', text: oldLines[i] })
      i++; j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      out.push({ type: 'del', text: oldLines[i] })
      i++
    } else {
      out.push({ type: 'add', text: newLines[j] })
      j++
    }
  }
  while (i < n) out.push({ type: 'del', text: oldLines[i++] })
  while (j < m) out.push({ type: 'add', text: newLines[j++] })
  return out
}
