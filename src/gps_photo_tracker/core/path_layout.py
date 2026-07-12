"""COPY 输出结构的路径布局工具。"""
from pathlib import Path


def lowest_common_ancestor(paths) -> Path | None:
    """所有路径最深的共同祖先目录；无共同根分量返回 None。"""
    if not paths:
        return None
    chains = []
    for p in paths:
        rp = Path(p).resolve()
        anchor = rp if rp.is_dir() else rp.parent
        chains.append(anchor.parts)
    common = []
    for tup in zip(*chains):
        if len(set(tup)) == 1:
            common.append(tup[0])
        else:
            break
    return Path(*common) if common else None
