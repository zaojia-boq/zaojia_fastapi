# -*- coding: utf-8 -*-
"""TF-IDF + 余弦相似度匹配器（M3 算法升级，第二阶段）。

替代 rapidfuzz 编辑距离，更适合中文长文本匹配。

设计：
- 纯函数模式（与 data/match_score.py 同模式），不依赖数据库
- 使用 scikit-learn TfidfVectorizer + 余弦相似度
- 中文分词使用 jieba
- 预计算物料字典的 TF-IDF 向量，匹配时 O(N) 计算余弦相似度
- 与 rapidfuzz 结果融合（加权平均），兼顾精确匹配和语义匹配

使用方式：
    matcher = TfidfMatcher(dict_rows)
    cands = matcher.match(query_name, query_spec, top_n=5)
"""
import re
from typing import Optional

import jieba
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


# 停用词（常见无意义词）
_STOP_WORDS = {
    '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一',
    '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有',
    '看', '好', '自己', '这', '那', '他', '她', '它', '们', '这个', '那个',
    '什么', '怎么', '为什么', '哪', '哪里', '谁', '多少', '几', '些',
}


def _tokenize(text: str) -> list[str]:
    """中文分词 + 清洗。"""
    if not text:
        return []
    # 去除特殊字符，保留中文、英文、数字
    text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', ' ', text)
    # jieba 分词
    words = jieba.lcut(text)
    # 过滤停用词和单字
    return [w.strip() for w in words if w.strip() and len(w.strip()) > 1 and w.strip() not in _STOP_WORDS]


def _build_doc(name: str, spec: str, category_path: str = '') -> str:
    """构建文档文本（名称 + 规格 + 分类路径，空格分隔）。"""
    parts = [name or '', spec or '']
    if category_path:
        # 分类路径按 / 拆分，加入分词
        parts.extend(category_path.split('/'))
    return ' '.join(p for p in parts if p)


class TfidfMatcher:
    """TF-IDF 匹配器。

    用法：
        matcher = TfidfMatcher(dict_rows)
        cands = matcher.match('电力电缆', 'YJV', top_n=5)
    """

    def __init__(self, dict_rows: list[dict]):
        """初始化匹配器。

        Args:
            dict_rows: 物料字典行列表，每行含 id/name/spec/category_path
        """
        self.dict_rows = dict_rows or []
        self._vectorizer: Optional[TfidfVectorizer] = None
        self._tfidf_matrix = None
        self._build_index()

    def _build_index(self):
        """构建 TF-IDF 索引。"""
        if not self.dict_rows:
            return

        docs = [
            _build_doc(
                row.get('name', ''),
                row.get('spec', ''),
                row.get('category_path', ''),
            )
            for row in self.dict_rows
        ]

        # 自定义分词器
        self._vectorizer = TfidfVectorizer(
            tokenizer=_tokenize,
            token_pattern=None,  # 使用自定义 tokenizer
            max_features=10000,
            ngram_range=(1, 2),  # 一元 + 二元词组
        )
        self._tfidf_matrix = self._vectorizer.fit_transform(docs)

    def match(self, query_name: str, query_spec: str, top_n: int = 5) -> list[dict]:
        """匹配查询。

        Args:
            query_name: 清单项名称
            query_spec: 清单项规格
            top_n: 返回 Top-N 候选

        Returns:
            候选列表，按相似度降序，每项含 dict_id/name/spec/score/category_path
        """
        if not self.dict_rows or self._tfidf_matrix is None:
            return []

        query_doc = _build_doc(query_name, query_spec)
        if not query_doc.strip():
            return []

        # 转换查询为 TF-IDF 向量
        query_vec = self._vectorizer.transform([query_doc])

        # 计算余弦相似度
        similarities = cosine_similarity(query_vec, self._tfidf_matrix).flatten()

        # 获取 Top-N 索引
        top_indices = similarities.argsort()[-top_n:][::-1]

        results = []
        for idx in top_indices:
            score = float(similarities[idx]) * 100  # 归一化到 0-100
            if score <= 0:
                continue
            row = self.dict_rows[idx]
            results.append({
                'dict_id': row.get('id'),
                'name': row.get('name', ''),
                'spec': row.get('spec', ''),
                'score': round(score, 2),
                'category_path': row.get('category_path', ''),
            })

        return results


def match_with_tfidf(
    query_name: str,
    query_spec: str,
    dict_rows: list[dict],
    top_n: int = 5,
) -> list[dict]:
    """便捷函数：一次性匹配（每次重新构建索引，适合小数据量）。

    大数据量请使用 TfidfMatcher 类，复用索引。
    """
    matcher = TfidfMatcher(dict_rows)
    return matcher.match(query_name, query_spec, top_n=top_n)


def fuse_scores(
    rapidfuzz_cands: list[dict],
    tfidf_cands: list[dict],
    rapidfuzz_weight: float = 0.5,
    tfidf_weight: float = 0.5,
) -> list[dict]:
    """融合 rapidfuzz 和 TF-IDF 的匹配结果（加权平均）。

    Args:
        rapidfuzz_cands: rapidfuzz 候选列表
        tfidf_cands: TF-IDF 候选列表
        rapidfuzz_weight: rapidfuzz 权重
        tfidf_weight: TF-IDF 权重

    Returns:
        融合后的候选列表，按综合分数降序
    """
    # 按 dict_id 建立索引
    rf_map = {c['dict_id']: c for c in rapidfuzz_cands}
    tf_map = {c['dict_id']: c for c in tfidf_cands}

    # 合并所有 dict_id
    all_ids = set(rf_map.keys()) | set(tf_map.keys())

    fused = []
    for dict_id in all_ids:
        rf_cand = rf_map.get(dict_id)
        tf_cand = tf_map.get(dict_id)

        rf_score = rf_cand['score'] if rf_cand else 0.0
        tf_score = tf_cand['score'] if tf_cand else 0.0

        # 加权平均（只有一个来源时，另一个权重归到有来源的那个）
        if rf_cand and tf_cand:
            combined = rapidfuzz_weight * rf_score + tfidf_weight * tf_score
        elif rf_cand:
            combined = rf_score
        else:
            combined = tf_score

        # 取有来源的候选信息
        base = rf_cand or tf_cand
        fused.append({
            'dict_id': dict_id,
            'name': base['name'],
            'spec': base['spec'],
            'score': round(combined, 2),
            'category_path': base.get('category_path', ''),
            'rf_score': rf_score,
            'tf_score': tf_score,
        })

    fused.sort(key=lambda c: c['score'], reverse=True)
    return fused
