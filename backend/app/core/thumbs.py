"""封面缩略图（R-179）：按需生成 + 落盘缓存。

背景（实测）：封面是原图直存（1766 张、平均 191KB、p90 503KB、最大 1MB、共 330MB），
素材库首屏已可见的 28 张就要下 13MB —— 分页只解决「拿多少条」，字节还得靠缩略图。

约定：
- `/covers/<name>?w=400` → 生成并缓存 `covers/thumbs/<name>.w400.jpg`（原子写，命中直接返回）；
- 不带 `w` 仍然走原图（静态挂载兜底），老代码/深链不受影响；
- 只处理图片扩展名；宽高夹在 `MIN_WIDTH..MAX_WIDTH`，非图片/超界一律回落原图。
"""

from __future__ import annotations

import io
from pathlib import Path

MIN_WIDTH = 80
MAX_WIDTH = 1200
THUMB_DIRNAME = "thumbs"
THUMB_QUALITY = 82

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}


def clamp_width(w: int | None) -> int | None:
    """非法/缺失宽度返回 None（= 不生成缩略图，走原图）。"""
    if w is None:
        return None
    try:
        value = int(w)
    except (TypeError, ValueError):
        return None
    if value < MIN_WIDTH:
        return MIN_WIDTH
    return min(value, MAX_WIDTH)


def thumb_file(covers_dir: Path, name: str, width: int) -> Path:
    """缩略图缓存路径（与原图同目录树下的 `thumbs/`）。"""
    safe = name.replace("\\", "/").lstrip("/")
    return covers_dir / THUMB_DIRNAME / f"{safe}.w{width}.jpg"


def make_thumb(src: Path, dest: Path, width: int) -> bool:
    """生成缩略图（JPEG）。失败返回 False（调用方回落原图，绝不因缩图失败而 500）。"""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - 依赖未装时退回原图
        return False
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as raw:
            img: Image.Image = raw.convert("RGB")  # 统一 JPEG（封面无透明需求）
            if img.width > width:
                height = max(1, round(img.height * width / img.width))
                img = img.resize((width, height), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=THUMB_QUALITY, optimize=True, progressive=True)
        # 原子写：先写临时文件再 rename，避免并发请求读到半个文件
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(buf.getvalue())
        tmp.replace(dest)
        return True
    except Exception:  # noqa: BLE001  坏图/权限问题都回落原图
        return False


def prewarm(covers_dir: Path, width: int = 400, *, pause: float = 0.02, limit: int | None = None) -> int:
    """把还缺的缩略图补齐（历史封面一次性预热；已有的一律跳过）。

    返回本次生成数量。`pause` 是每张之间的停顿，避免在 NAS 上抢 CPU/磁盘。
    """
    import time

    if not covers_dir.is_dir():
        return 0
    made = 0
    for src in sorted(covers_dir.iterdir()):
        if not src.is_file() or src.suffix.lower() not in IMAGE_EXTS:
            continue
        dest = thumb_file(covers_dir, src.name, width)
        if dest.is_file():
            continue
        if make_thumb(src, dest, width):
            made += 1
            if limit is not None and made >= limit:
                break
        time.sleep(pause)
    return made


def prewarm_async(covers_dir: Path, width: int = 400, *, logger=None) -> None:
    """后台线程预热（启动时调用；失败只记日志，绝不影响启动）。"""

    import threading

    def _run() -> None:
        try:
            made = prewarm(covers_dir, width)
            if made and logger is not None:
                logger.info("封面缩略图预热完成：本次生成 %d 张（缓存目录 %s）", made, covers_dir / THUMB_DIRNAME)
        except Exception as exc:  # noqa: BLE001
            if logger is not None:
                logger.warning("封面缩略图预热失败（不影响使用）：%s", exc)

    threading.Thread(target=_run, name="cover-thumb-prewarm", daemon=True).start()
