"""COPY 输出结构的路径布局工具。"""
from pathlib import Path


def lowest_common_ancestor(paths) -> Path | None:
    """所有路径最深的共同祖先目录；无共同根分量返回 None。

    用字面路径（不 resolve 符号链接 / 盘符）：与 ``result.photo.path``（来自
    ``rglob`` 的字面路径）保持一致，使 ``_copy_destination`` 的
    ``src.relative_to(photo_dir)`` 在所有平台都能命中。``resolve()`` 在 Windows
    会给 ``/foo`` 注入当前盘符（``D:/foo``）、在 macOS 会把 ``/var`` 解析成
    ``/private/var``，反而让 LCA 不再是字面父目录、``relative_to`` 失败。
    """
    if not paths:
        return None
    chains = []
    for p in paths:
        pp = Path(p)
        anchor = pp if pp.is_dir() else pp.parent
        chains.append(anchor.parts)
    common = []
    for tup in zip(*chains):
        if len(set(tup)) == 1:
            common.append(tup[0])
        else:
            break
    return Path(*common) if common else None
