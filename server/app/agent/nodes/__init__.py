"""节点实现（W3 D11 起）。

每个节点是纯函数：`(state, deps) -> dict`，返回 state 的增量。
节点内不发事件、不直接写库、不直接调 HTTP —— 副作用交给 runtime 与 tools。
"""
