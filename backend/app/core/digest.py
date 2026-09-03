
"""纯逻辑（无第三方依赖）：每日邮件 HTML 构造。"""

from __future__ import annotations

def build_digest_html(items: list[dict], web_base_url: str = "") -> str:
    """构造每日选题邮件 HTML。

    items: [{"title", "platform", "score", "reason", "draft_id", "cover_text", "script"}]
    """
    rows = []
    for i, item in enumerate(items, 1):
        platform = item.get("platform") or "综合"
        link = f"{web_base_url.rstrip('/')}/#/drafts/{item.get('draft_id')}" if item.get("draft_id") else ""
        link_html = f' <a href="{link}">去工作台</a>' if link else ""
        rows.append(
            "<div style='margin-bottom:18px;padding:14px;border:1px solid #e5e7eb;border-radius:10px'>"
            f"<h3 style='margin:0 0 4px'>{i}. {item.get('title','')}</h3>"
            f"<p style='margin:2px 0;color:#666'>平台：{platform} · 匹配度：{item.get('score',0)} · "
            f"{item.get('reason','')}{link_html}</p>"
            f"<p style='margin:6px 0;color:#888'>封面字：{item.get('cover_text','') or '（无）'}</p>"
            f"<p style='white-space:pre-wrap;line-height:1.7'>{item.get('script','')}</p>"
            "</div>"
        )
    return (
        "<html><body style='font-family:sans-serif;max-width:680px;margin:0 auto;padding:16px'>"
        "<h2>echo · 今日选题与脚本</h2>"
        + "".join(rows)
        + "<p style='color:#999;font-size:12px'>本邮件由 echo 自动生成。直接采用并发布，就是对人设学习最好的反馈。</p>"
        "</body></html>"
    )


def build_failure_html(error: str) -> str:
    return (
        "<html><body style='font-family:sans-serif'>"
        "<h2>echo · 今日流水线运行失败</h2>"
        f"<p>错误信息：<code>{error}</code></p>"
        "<p>可在 Web 端「看板 → 流水线状态」查看，或手动触发重跑。</p>"
        "</body></html>"
    )
