"""纯逻辑（无第三方依赖）：改稿差异判断。"""
from .transcript import normalize_text


def has_meaningful_change(original: str, edited: str) -> bool:
    """判断作者是否对 AI 原稿做了有意义的改写（规范化后不同且都不为空）。"""
    a, b = normalize_text(original), normalize_text(edited)
    if not a or not b:
        return False
    return a != b
