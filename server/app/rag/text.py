"""检索用的文本归一化与分词。

Postgres 自带的分词器对中文是按「连续汉字串」处理的，`to_tsvector('simple', ...)`
拿到"打印机离线"会生成一个 token，BM25 基本失效。v0 不引入 zhparser（需要
自定义词典与扩展），而是在应用层做确定性切分：

- ASCII：小写单词（保留型号/错误码里的 `-` / `_` / `.`）
- 中文：单字 + 相邻二元组

单字保证"连不上"和"无法连接"至少共享"连"；二元组保证"打印机"这类词有区分度。
切好的 token 用空格拼成一个 text 列，Postgres 只负责倒排与打分（见索引代码）。

这个选择写进了 docs/decisions/0011-offline-rag-vectorizer.md。
"""

from __future__ import annotations

import re

_ASCII_TOKEN = re.compile(r"[a-z0-9][a-z0-9._/-]*", re.IGNORECASE)
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")

#: 高频虚词/泛化办公词不参与召回（单字仍保留，避免句子被切得太碎）。
#: 泛化词（公司/规则/说明…）几乎出现在每篇文档里，保留会让负样本也越过阈值。
STOPWORDS: frozenset[str] = frozenset(
    [
        "的",
        "了",
        "是",
        "在",
        "和",
        "与",
        "或",
        "及",
        "有",
        "我",
        "你",
        "他",
        "她",
        "它",
        "这",
        "那",
        "哪",
        "吗",
        "呢",
        "啊",
        "吧",
        "呀",
        "么",
        "一个",
        "我们",
        "你们",
        "他们",
        "什么",
        "怎么",
        "如何",
        "为什么",
        "可以",
        "需要",
        "进行",
        "使用",
        "相关",
        "服务",
        "公司",
        "员工",
        "工作",
        "问题",
        "说明",
        "指南",
        "规则",
        "事项",
        "办理",
        "注意",
        "以上",
        "以下",
        "如果",
        "告诉",
    ]
)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def tokenize(text: str) -> list[str]:
    """返回去重后的 token 列表，保持首次出现顺序。"""
    normalized = normalize(text)
    seen: set[str] = set()
    tokens: list[str] = []

    def add(token: str) -> None:
        if not token or token in STOPWORDS or token in seen:
            return
        seen.add(token)
        tokens.append(token)

    for match in _ASCII_TOKEN.finditer(normalized):
        add(match.group(0).strip("._/-"))
    for match in _CJK_RUN.finditer(normalized):
        run = match.group(0)
        for char in run:
            add(char)
        for index in range(len(run) - 1):
            add(run[index : index + 2])
    return tokens


def token_text(text: str) -> str:
    """给 Postgres 用的 token 串；空串表示没有可检索内容。"""
    return " ".join(tokenize(text))


def token_set(text: str) -> set[str]:
    return set(tokenize(text))


def token_weights(text: str) -> dict[str, float]:
    """查询覆盖度用的权重：二元组/英文词权重高于单字。

    负样本（"公司年会抽奖规则"）里能命中的通常只有"会""规则"这类泛化 token；
    如果按个数算覆盖率会虚高。按权重算 + 停用词过滤后，这类问题会稳定低于阈值。
    """
    weights: dict[str, float] = {}
    for token in expand_tokens(tokenize(text)):
        weights[token] = 2.0 if len(token) >= 2 else 1.0
    return weights


#: 极小的领域同义词：只补「用户口语 vs 文档用词」的高频差异。
#: 不是通用同义词库 —— 每加一个都要有评测用例兜底，避免把负样本拉过阈值。
SYNONYMS: dict[str, tuple[str, ...]] = {
    "邮件": ("邮箱",),
    "邮箱": ("邮件",),
    "过保": ("保修", "维修"),
    "保修": ("过保",),
    "附件": ("文件",),
    "屏幕": ("显示器",),
    "显示器": ("屏幕",),
    "花钱": ("付费", "费用"),
    "付费": ("费用", "花钱"),
    "费用": ("付费", "花费"),
}


def expand_tokens(tokens: list[str]) -> list[str]:
    expanded: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        for candidate in (token, *SYNONYMS.get(token, ())):
            if candidate not in seen:
                seen.add(candidate)
                expanded.append(candidate)
    return expanded


def weighted_coverage(query_weights: dict[str, float], document_tokens: set[str]) -> float:
    total = sum(query_weights.values())
    if total <= 0:
        return 0.0
    matched = sum(weight for token, weight in query_weights.items() if token in document_tokens)
    return matched / total
