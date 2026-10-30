"""R-233：生成/洗稿的「联网参考」证据层（豆包 + DeepSeek 双源）。

流水线：
1. 双源并行检索（豆包 = 摘要/短正文；DeepSeek = Search 自带正文）；
2. 合并去重（URL 归一化 + 标题近重）→ 文章类型过滤 → 营销规则剔除 → 选题相关度过滤；
3. 缺正文的候选调 DeepSeek Fetch 补齐（反爬站点失败就退回摘要），按相关度抽段截到 2000 字；
4. 由生成方模型按当前主博主人设选 2–3 篇并给理由（失败自动兜底），只把选中文正文注入 prompt；
5. 豆包 / DeepSeek 各写一行 `web_search_logs` 留痕，引用回写 `used`。

设计约束：
- 无 key / 单路失败 / 选文失败 → 全部静默降级，绝不阻断生成；
- 营销内容只在规则层剔除（域名 + 转化话术 + 电商域），边界情况交给选文提示词兜底。
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.log import get_logger
from ..models.web_search import WebSearchLog
from . import deepseek_search, web_search

log = get_logger("evidence")

_MAX_QUERY = 100  # 豆包搜索建议 query 1~100 字（DeepSeek 1~128，取交集）
_SPLIT_RE = re.compile(r"[\s，。！？!?,.;:：、|\[\]()（）《》“”\"'…\-—#＃]+")
_SENTENCE_RE = re.compile(r"[^。！？!?\n]+[。！？!?]?")

# 追踪参数（去重时丢掉，避免同一篇因渠道参数被当成两条）
_TRACKING_PREFIX = ("utm_",)
_TRACKING_KEYS = {"spm", "from", "source", "share", "scene", "click_id", "sharer"}

# 代码/仓库页：DeepSeek 会把 GitHub 的 skill/README 文件搜进来（实测）
_CODE_HOSTS = {"github.com", "gist.github.com", "gitlab.com", "raw.githubusercontent.com"}
_FILE_SUFFIX = (".zip", ".rar", ".7z", ".exe", ".dmg", ".apk", ".tar", ".gz")

# 转化话术（标题命中一个即判营销；正文命中 ≥3 个不同信号才判）
_CTA_RE = re.compile(
    r"加微信|加\s*[vV]|扫码|扫一扫|私信|进群|领取|免费领|报名|下单|购买|优惠|折扣|"
    r"直播间|橱窗|限时|返现|团购|秒杀|训练营|陪跑|代运营|招生|一对一|私教"
)
_COURSE_RE = re.compile(r"课程|训练营|陪跑|代运营|招生")
_DEAL_RE = re.compile(r"报名|咨询|价格|费用|购买|领取|扫码|加微信|私信")

# 电商域（即使作者清空站点黑名单，也不该拿商品页当参考）
_COMMERCE_HOSTS = (
    "taobao.com",
    "tmall.com",
    "jd.com",
    "pinduoduo.com",
    "1688.com",
    "alibaba.com",
    "youzan.com",
    "xiaohongshu.com/goods",
)

_PICK_SYSTEM = (
    "你是这位博主的脚本策划。下面是一批为口播选题检索到的候选文章，请只挑出最适合当参考的 "
    "{min_pick}~{max_pick} 篇：优先能提供**具体事实、数据、案例、反常识观点**，并且与博主的人设、"
    "立场、受众一致；营销/卖课/引流/带货/通稿一律不选（即使标题相关）。"
    "理由必须写清「这篇能提供什么事实/案例/观点」，不要写「写得好」「相关」。"
    '只输出 JSON：{{"picks":[{{"id":1,"reason":"..."}}],"reject":[{{"id":2,"reason":"..."}}]}}'
)


def build_search_query(topic: str, material: str = "") -> str:
    """构造搜索词：选题 + 该入口能拿到的最具体文本（截断到 100 字）。"""
    topic = (topic or "").strip()
    material = re.sub(r"\s+", " ", (material or "").strip())
    if not material:
        return topic[:_MAX_QUERY].strip()
    room = max(0, _MAX_QUERY - len(topic) - 1)
    return f"{topic} {material[:room]}".strip()


def _grams(text: str) -> set[str]:
    """粗分词：按标点切词，词长>2 时取相邻双字 bigram（对中文友好，零依赖）。"""
    out: set[str] = set()
    for word in _SPLIT_RE.split(text or ""):
        word = word.strip()
        if not word:
            continue
        if len(word) <= 2:
            out.add(word)
        else:
            out.update(word[i : i + 2] for i in range(len(word) - 1))
    return out


def _title_key(text: str) -> str:
    return re.sub(r"[\W_]+", "", (text or "").lower(), flags=re.UNICODE)


def _title_similar(a: str, b: str) -> bool:
    ga, gb = _grams(a), _grams(b)
    if not ga or not gb:
        return False
    return len(ga & gb) / len(ga | gb) >= 0.8


def _norm_url(url: str) -> str:
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return (url or "").strip().lower()
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING_PREFIX) and k.lower() not in _TRACKING_KEYS
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def filter_relevant(query: str, sources: list[dict], min_score: int | None = None) -> list[dict]:
    """过滤不相关结果：关键词重叠度低于阈值即丢弃；全不相关返回 []（不硬塞）。"""
    if not sources:
        return []
    q = _grams(query)
    if not q:
        return sources
    thr = min_score if min_score is not None else (1 if len(q) <= 6 else 2)
    out: list[dict] = []
    for s in sources:
        score = len(q & _grams(f"{s.get('title') or ''} {s.get('summary') or ''}"))
        if score >= thr:
            out.append(s)
    return out


def _relevance_score(item: dict, qgrams: set[str]) -> int:
    return len(qgrams & _grams(f"{item.get('title') or ''} {item.get('summary') or ''}"))


def _article_reason(item: dict) -> str:
    """代码仓库页/文件下载页：不是文章，不能当口播参考。"""
    try:
        parts = urlsplit(item.get("url") or "")
    except ValueError:
        return ""
    host = parts.netloc.lower()
    path = parts.path.lower()
    if host in _CODE_HOSTS and ("/blob/" in path or "/skills/" in path or path.endswith(".md")):
        return "代码/仓库页"
    if path.endswith(_FILE_SUFFIX):
        return "文件下载页"
    return ""


def _marketing_reason(item: dict, blacklist: list[str]) -> str:
    url = (item.get("url") or "").lower()
    try:
        host = urlsplit(url).netloc
    except ValueError:
        host = ""
    for site in blacklist:
        if site and site in url:
            return f"站点黑名单：{site}"
    for host_part in _COMMERCE_HOSTS:
        if host_part in host:
            return f"电商/带货域：{host_part}"

    title = (item.get("title") or "").strip()
    text = " ".join(
        x for x in (title, item.get("summary") or "", (item.get("content") or "")[:300]) if x
    )
    hits = sorted(set(_CTA_RE.findall(title)))
    if hits:
        return "标题含转化话术：" + "、".join(hits[:3])
    if _COURSE_RE.search(title) and _DEAL_RE.search(text):
        return "课程/招生类内容"
    body_hits = sorted(set(_CTA_RE.findall(text)))
    if len(body_hits) >= 3:
        return "正文反复引流：" + "、".join(body_hits[:3])
    return ""


def _merge_item(into: dict, extra: dict) -> None:
    """同篇合并：保留更长的正文/摘要，补齐站点/日期/权威度，并记录双 provider。"""
    for key in ("content", "summary", "snippet", "site", "date", "url"):
        if len(str(extra.get(key) or "")) > len(str(into.get(key) or "")):
            into[key] = extra.get(key)
    try:
        into["rank"] = max(float(into.get("rank") or 0), float(extra.get("rank") or 0))
    except (TypeError, ValueError):
        pass
    try:
        into["authority"] = max(int(into.get("authority") or -1), int(extra.get("authority") or -1))
    except (TypeError, ValueError):
        pass
    providers = {str(p) for p in (into.get("providers") or [into.get("provider")]) if p}
    providers.update(str(p) for p in (extra.get("providers") or [extra.get("provider")]) if p)
    into["providers"] = sorted(providers)


def _dedupe(items: list[dict]) -> list[dict]:
    """URL 归一化去重 + 标题近重去重（中文 bigram Jaccard ≥0.8）。"""
    out: list[dict] = []
    by_url: dict[str, dict] = {}
    for raw in items:
        item = dict(raw)
        url_key = _norm_url(item.get("url") or "")
        if url_key and url_key in by_url:
            _merge_item(by_url[url_key], item)
            continue
        title = (item.get("title") or "").strip()
        dup = next((x for x in out if title and _title_similar(title, x.get("title") or "")), None)
        if dup is not None:
            _merge_item(dup, item)
            continue
        if url_key:
            by_url[url_key] = item
        out.append(item)
    return out


def _score(item: dict, qgrams: set[str]) -> float:
    """排序分：相关度（主）+ provider 内名次 + 正文长度（轻）。

    豆包 RankScore≈1、DeepSeek rerank_score 0~3、权威度两边量纲也不同，
    直接比会系统性偏袒某一路 → 统一用「该路内部名次」。
    """
    rel = _relevance_score(item, qgrams)
    try:
        rank_norm = min(max(float(item.get("provider_rank") or 0.0), 0.0), 1.0)
    except (TypeError, ValueError):
        rank_norm = 0.0
    richness = min(len(item.get("content") or "") / 4000.0, 1.0)
    return rel + rank_norm * 2.0 + richness * 0.2


def _trim_content(text: str, topic: str, persona: str, limit: int) -> str:
    """保留开头 400 字，再按与「选题 + 人设」的相关度抽段补到 limit（不硬切半句）。"""
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    head = text[:400]
    tail = text[400:]
    qgrams = _grams(f"{topic} {persona}")
    segments = [s.strip() for s in _SENTENCE_RE.findall(tail) if s.strip()]
    ranked = sorted(enumerate(segments), key=lambda pair: (-len(qgrams & _grams(pair[1])), pair[0]))
    picked: list[tuple[int, str]] = []
    used = len(head)
    for idx, seg in ranked:
        if used + len(seg) > limit:
            continue
        picked.append((idx, seg))
        used += len(seg)
    picked.sort()
    extra = "".join(seg for _, seg in picked)
    if not extra:  # 全文无句号（或所有段落都超预算）→ 硬截，至少别只剩开头 400 字
        extra = tail[: max(0, limit - len(head))]
    return head + extra


def _fill_content(items: list[dict], topic: str, persona: str, budget: float) -> None:
    """缺正文的候选调 DeepSeek Fetch 补齐；超预算/失败就保留 Search 自带内容或摘要。"""
    settings = get_settings()
    if not settings.online_fetch_enabled or not deepseek_search.enabled():
        return
    def _needs_fetch(item: dict) -> bool:
        content = (item.get("content") or "").strip()
        summary = (item.get("summary") or "").strip()
        # 豆包 Content 与 Summary 等长（只是短摘要），同样值得再 Fetch 一次正文
        return not content or content == summary or len(content) < int(
            settings.online_min_content_chars
        )

    need = [item for item in items if item.get("url") and _needs_fetch(item)][
        : max(0, int(settings.online_fetch_max))
    ]
    if not need:
        return
    started = time.monotonic()
    executor = ThreadPoolExecutor(max_workers=min(3, len(need)))
    futures = {executor.submit(deepseek_search.fetch, str(item["url"])): item for item in need}
    try:
        for future in as_completed(futures, timeout=max(3.0, budget)):
            item = futures[future]
            try:
                text = future.result()
            except Exception as exc:  # noqa: BLE001 单篇抓取失败不阻断
                log.warning("正文抓取失败（%s）：%s", item.get("url"), str(exc)[:120])
                continue
            if text and len(text) > len(item.get("content") or ""):
                item["content"] = text
                item["fetched"] = True
    except FuturesTimeout:
        log.warning("正文抓取超出预算 %.1fs，用已有内容继续", budget)
        for future in futures:
            future.cancel()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
        log.info("正文补齐 %.1fs：%d 篇候选", time.monotonic() - started, len(need))


def _trim_all(items: list[dict], topic: str, persona: str) -> None:
    limit = max(400, int(get_settings().online_fetch_chars or 2000))
    for item in items:
        raw = (item.get("content") or "").strip()
        item["content_chars"] = len(raw)
        if raw:
            item["content"] = _trim_content(raw, topic, persona, limit)


def _auto_pick(candidates: list[dict], count: int) -> list[dict]:
    picked: list[dict] = []
    for item in candidates[: max(0, count)]:
        chosen = dict(item)
        chosen["reason"] = "自动兜底：按选题相关度与来源排序选取"
        chosen["picked"] = True
        picked.append(chosen)
    return picked


def _pick_llm(picker, messages: list[dict], timeout_seconds: int) -> dict:
    """选文调用（R-240 M6）：把单次墙钟预算下沉到 LLM 客户端。

    软超时（`future.result(timeout=…)`）只是「不再等待」，取消不了已在跑的线程；
    把 `timeout_seconds` 传下去后，底层调用最多跑到这个预算（原来会一直跑到 600s 上限）。
    注入的旧客户端/测试替身不接受该参数时退回普通调用（R-233 兼容）。
    """
    from .llm import accepts_timeout

    kwargs = {"temperature": 0.3, "max_tokens": 800, "require": ("picks",)}
    if accepts_timeout(picker.chat_json):
        kwargs["timeout_seconds"] = timeout_seconds
    # R-240 复核修复：用签名探测代替 try/except TypeError，避免客户端内部 TypeError 被当成
    # 「签名不兼容」而把同一次选文调用重发一遍。
    return picker.chat_json(messages, **kwargs)


def select_references(
    picker,
    candidates: list[dict],
    *,
    topic: str,
    persona: str = "",
    min_pick: int | None = None,
    max_pick: int | None = None,
) -> list[dict]:
    """生成方按人设选 2–3 篇：返回带 `reason/picked` 的候选副本；失败自动兜底。"""
    settings = get_settings()
    lo = max(1, int(min_pick if min_pick is not None else settings.online_ref_pick_min or 2))
    hi = max(lo, int(max_pick if max_pick is not None else settings.online_ref_pick_max or 3))
    pool = [c for c in candidates if (c.get("title") or c.get("url"))][: max(hi * 4, 8)]
    if not pool:
        return []
    if picker is None:
        return _auto_pick(pool, hi)

    lines: list[str] = []
    for i, item in enumerate(pool, 1):
        head = item.get("title") or item.get("url") or ""
        meta = " · ".join(
            x for x in (item.get("site"), (item.get("date") or "")[:10], item.get("provider")) if x
        )
        summary = (item.get("summary") or item.get("snippet") or item.get("content") or "")[:200]
        lines.append(f"[{i}] {head}" + (f"（{meta}）" if meta else ""))
        if summary:
            lines.append(f"    {summary}")
    system = _PICK_SYSTEM.format(min_pick=lo, max_pick=hi)
    user = (
        f"【博主人设】\n{persona[:1500] or '（暂无）'}\n\n"
        f"【选题】{topic}\n\n"
        "【候选文章】\n" + "\n".join(lines)
    )
    timeout = max(1.0, float(settings.online_pick_timeout_seconds or 45))
    # R-240 M6：选文调用单次墙钟预算 ≤45s（与软超时同值，配置更小则跟配置）。
    # 这样软超时放弃等待后，底层线程最多再跑这么久，不会像原来那样漏到 600s。
    call_timeout = int(max(1.0, min(45.0, timeout)))
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(
        _pick_llm,
        picker,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        call_timeout,
    )
    try:
        data = future.result(timeout=timeout)
    except FuturesTimeout:
        # 选文只是锦上添花：生成方模型偶尔长挂（思考/网络），到点直接按相关度兜底
        log.warning("生成方选文超时 %.0fs，自动兜底", timeout)
        future.cancel()
        return _auto_pick(pool, hi)
    except Exception as exc:  # noqa: BLE001 选文失败 → 自动兜底，不阻断生成
        log.warning("生成方选文失败，自动兜底：%s", str(exc)[:160])
        return _auto_pick(pool, hi)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    picked: list[dict] = []
    seen: set[str] = set()
    raw_picks = data.get("picks")
    for raw in raw_picks if isinstance(raw_picks, list) else []:
        if not isinstance(raw, dict):
            continue
        try:
            idx = int(str(raw.get("id")).strip())
        except (TypeError, ValueError):
            continue
        if not 1 <= idx <= len(pool):
            continue
        item = pool[idx - 1]
        key = _norm_url(item.get("url") or "") or _title_key(item.get("title") or "")
        if key in seen:
            continue
        seen.add(key)
        chosen = dict(item)
        chosen["reason"] = str(raw.get("reason") or "").strip()[:200] or "生成方选中"
        chosen["picked"] = True
        picked.append(chosen)
        if len(picked) >= hi:
            break

    # 不足下限：按排序补足（选文模型偶尔只给 1 篇）
    if len(picked) < lo:
        for item in pool:
            if len(picked) >= lo:
                break
            key = _norm_url(item.get("url") or "") or _title_key(item.get("title") or "")
            if key in seen:
                continue
            seen.add(key)
            chosen = dict(item)
            chosen["reason"] = "生成方未点名，按相关度补足"
            chosen["picked"] = True
            picked.append(chosen)
    return picked


def _build_block(sources: list[dict]) -> str:
    if not sources:
        return ""
    lines = [
        "【联网事实素材·生成方已按人设选文（营销内容已排除）；只能引用以下参考里的真实事实/数据/观点，"
        "必须口语化转述（不要念 URL），不得编造】"
    ]
    for i, item in enumerate(sources, 1):
        head = item.get("title") or item.get("site") or ""
        meta = " ".join(
            x
            for x in (
                item.get("site"),
                (item.get("date") or "")[:10],
                item.get("url"),
            )
            if x
        )
        lines.append(f"[{i}] {head}" + (f"（{meta}）" if meta else ""))
        reason = (item.get("reason") or "").strip()
        if reason:
            lines.append(f"    选文理由：{reason[:160]}")
        body = (item.get("content") or item.get("summary") or "").strip()
        if body:
            lines.append(f"    正文节选：{body[:2400]}")
    return "\n".join(lines)


def _write_logs(
    db: Session,
    *,
    draft_id: int | None,
    creator_id: int | None,
    query: str,
    time_range: str,
    by_provider: dict[str, dict],
) -> list[int]:
    rows: list[WebSearchLog] = []
    for provider, payload in by_provider.items():
        row = WebSearchLog(
            draft_id=draft_id,
            creator_id=creator_id,
            query=query,
            source=provider,
            time_range=time_range or "",
            results=json.dumps(payload, ensure_ascii=False),
        )
        db.add(row)
        rows.append(row)
    if not rows:
        return []
    try:
        db.commit()
    except Exception:  # noqa: BLE001 留痕失败不影响生成
        db.rollback()
        log.exception("联网搜索留痕写入失败")
        return []
    return [row.id for row in rows if row.id]


def mark_logs_used(db: Session, log_ids: list[int], used: list[dict]) -> None:
    """回写「模型实际引用了哪几篇」（豆包/DeepSeek 两行都写，便于对账）。"""
    if not log_ids:
        return
    try:
        rows = db.query(WebSearchLog).filter(WebSearchLog.id.in_(log_ids)).all()
        payload = json.dumps(used, ensure_ascii=False)
        for row in rows:
            row.used = payload
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("联网留痕 used 回写失败")


def gather_online(
    db: Session,
    topic: str,
    *,
    material: str = "",
    draft_id: int | None = None,
    creator_id: int | None = None,
    count: int | None = None,
    time_range: str = "",
    persona: str = "",
    picker=None,
) -> dict:
    """双源检索 → 去重/过滤 → 补正文 → 生成方选文；返回可注入 prompt 的清单与留痕 id。

    返回 `{"sources", "selected", "queries", "block", "log_ids", "rejected"}`；
    无 key / 两路都不可用 → 返回 `{"sources": [], "queries": [], "block": ""}`（与 R-227 一致）。
    """
    query = build_search_query(topic, material)
    if not query:
        return {"sources": [], "queries": [], "block": ""}

    settings = get_settings()
    want = int(count or settings.web_search_count or 5)
    jobs: dict[str, tuple[int, float]] = {}
    if web_search.enabled():
        jobs["doubao"] = (want, float(settings.web_search_timeout_seconds or 15))
    if deepseek_search.enabled():
        jobs["deepseek"] = (
            int(settings.deepseek_search_count or want),
            float(settings.online_search_timeout_seconds or 20),
        )
    if not jobs:
        return {"sources": [], "queries": [], "block": ""}

    started = time.monotonic()
    raw: dict[str, dict] = {}
    executor = ThreadPoolExecutor(max_workers=len(jobs))
    futures = {}
    for provider, (n, _timeout) in jobs.items():
        submitted = time.monotonic()
        if provider == "doubao":
            fut = executor.submit(web_search.search, query, n, time_range, True)
        else:
            fut = executor.submit(deepseek_search.search, query, n, time_range)
        futures[fut] = (provider, n, submitted)
    try:
        for future in as_completed(futures, timeout=max(25.0, sum(t for _, t in jobs.values()))):
            provider, n, submitted = futures[future]
            try:
                items = future.result()
            except Exception as exc:  # noqa: BLE001 单路失败不影响另一路
                log.warning("%s 搜索失败：%s", provider, str(exc)[:160])
                items = []
            raw[provider] = {
                "items": [dict(x) for x in (items or []) if isinstance(x, dict)],
                "count": n,
                "elapsed_ms": int((time.monotonic() - submitted) * 1000),
            }
    except FuturesTimeout:
        log.warning("双源搜索超出预算，用已完成的结果继续")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    qgrams = _grams(query)
    thr = 1 if len(qgrams) <= 6 else 2
    blacklist = [
        s.strip().lower()
        for s in (settings.online_site_blacklist or "").split(",")
        if s.strip()
    ]

    kept: list[dict] = []
    rejected: list[dict] = []
    by_provider: dict[str, dict] = {}
    queries: list[dict] = []
    for provider, info in raw.items():
        kept_p: list[dict] = []
        rejected_p: list[dict] = []
        total_items = max(1, len(info["items"]))
        for pos, raw_item in enumerate(info["items"]):
            item = dict(raw_item)
            item["provider"] = item.get("provider") or provider
            # 双源分数量纲不同：记录「该路内名次」，供合并排序公平比较
            item["provider_rank"] = round(1.0 - pos / total_items, 4)
            reason = _article_reason(item) or _marketing_reason(item, blacklist)
            if not reason and _relevance_score(item, qgrams) < thr:
                reason = "与选题不相关"
            if reason:
                rejected_p.append(
                    {
                        "provider": provider,
                        "title": item.get("title") or "",
                        "url": item.get("url") or "",
                        "reason": reason,
                    }
                )
            else:
                kept_p.append(item)
        by_provider[provider] = {"kept": kept_p, "rejected": rejected_p}
        kept.extend(kept_p)
        rejected.extend(rejected_p)
        queries.append(
            {
                "provider": provider,
                "query": query,
                "count": info["count"],
                "time_range": time_range,
                "raw_count": len(info["items"]),
                "kept_count": len(kept_p),
                "elapsed_ms": info["elapsed_ms"],
            }
        )

    kept = _dedupe(kept)
    for item in kept:
        item["providers"] = item.get("providers") or [item.get("provider")]
    kept.sort(key=lambda item: _score(item, qgrams), reverse=True)

    if kept:
        elapsed = time.monotonic() - started
        budget = max(3.0, float(settings.online_budget_seconds or 25) - elapsed)
        _fill_content(kept, topic, persona, budget)
        _trim_all(kept, topic, persona)

    # 留痕用「补齐/裁剪后的最终版本」（含正文），但按 provider 分路保留
    final_by_url = {_norm_url(item.get("url") or ""): item for item in kept}
    for payload in by_provider.values():
        payload["kept"] = [
            final_by_url.get(_norm_url(item.get("url") or ""), item)
            for item in payload["kept"]
        ]

    selected: list[dict] = []
    if kept:
        if settings.online_ref_pick and picker is not None:
            selected = select_references(picker, kept, topic=topic, persona=persona)
        else:
            selected = _auto_pick(kept, int(settings.online_ref_pick_max or 3))

    log_ids = _write_logs(
        db,
        draft_id=draft_id,
        creator_id=creator_id,
        query=query,
        time_range=time_range,
        by_provider=by_provider,
    )
    return {
        "sources": kept,
        "selected": selected,
        "queries": queries,
        "block": _build_block(selected),
        "log_ids": log_ids,
        "rejected": rejected[:30],
    }


_PUBLIC_KEYS = (
    "title",
    "url",
    "site",
    "provider",
    "providers",
    "date",
    "reason",
    "content_chars",
    "picked",
)


def public_items(items: list[dict], limit: int = 20) -> list[dict]:
    """给 `Draft.quality` / 接口返回的轻量元数据：去掉正文，避免草稿列表被 10KB 级 JSON 拖慢。"""
    out: list[dict] = []
    for item in (items or [])[:limit]:
        out.append({key: item.get(key) for key in _PUBLIC_KEYS if item.get(key) is not None})
    return out


def resolve_used(sources: list[dict], used_indices) -> list[dict]:
    """把模型声明的引用编号（[1,3]）解析为真实来源，过滤越界编号（防编造来源）。"""
    out: list[dict] = []
    for raw in used_indices or []:
        try:
            idx = int(raw)
        except (TypeError, ValueError):
            continue
        if 1 <= idx <= len(sources):
            src = sources[idx - 1]
            if src not in out:
                out.append(src)
    return out
