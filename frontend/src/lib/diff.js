// 轻量字符级 diff：返回左右两列分段，用于「原文案 vs 洗稿后」对照高亮。
export function buildDiff(a, b) {
  const A = Array.from(a || '')
  const B = Array.from(b || '')
  const n = A.length
  const m = B.length
  const dp = new Array(n + 1)
  for (let i = 0; i <= n; i++) dp[i] = new Int32Array(m + 1)
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }

  const leftOps = []
  const rightOps = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (A[i] === B[j]) {
      leftOps.push({ t: 'same', ch: A[i] })
      rightOps.push({ t: 'same', ch: B[j] })
      i++
      j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      leftOps.push({ t: 'del', ch: A[i] })
      i++
    } else {
      rightOps.push({ t: 'add', ch: B[j] })
      j++
    }
  }
  while (i < n) {
    leftOps.push({ t: 'del', ch: A[i] })
    i++
  }
  while (j < m) {
    rightOps.push({ t: 'add', ch: B[j] })
    j++
  }

  return { left: group(leftOps), right: group(rightOps) }
}

function group(ops) {
  const segs = []
  for (const op of ops) {
    const last = segs[segs.length - 1]
    if (last && last.type === op.t) {
      last.text += op.ch
    } else {
      segs.push({ text: op.ch, type: op.t })
    }
  }
  return segs
}
