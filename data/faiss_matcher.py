# -*- coding: utf-8 -*-
"""FAISS 向量检索匹配器（M3 算法升级，第二阶段）。

亿级数据毫秒级检索，基于 Facebook AI Similarity Search (FAISS)。

设计：
- 纯函数模式（与 data/match_score.py / tfidf_matcher.py 同模式），不依赖数据库
- 使用 TF-IDF 向量化文本（复用 tfidf_matcher 的分词和向量化逻辑）
- 使用 FAISS IndexFlatIP（内积索引）存储归一化后的向量
- 查询时计算查询向量，FAISS 检索 Top-N 最近邻（O(log N) 复杂度）
- 与 rapidfuzz 和 TF-IDF 结果融合（三算法加权平均）

使用方式：
    matcher = FaissMatcher(dict_rows)
    cands = matcher.match(query_name, query_spec, top_n=5)
"""
import numpy as np
from typing import Optional

from data.tfidf_matcher import _tokenize, _build_doc

try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False


class FaissMatcher:
    """FAISS 向量检索匹配器。

    用法：
        matcher = FaissMatcher(dict_rows)
        cands = matcher.match('电力电缆', 'YJV', top_n=5)
    """

    def __init__(self, dict_rows: list[dict], vector_dim: int = 512):
        """初始化匹配器。

        Args:
            dict_rows: 物料字典行列表，每行含 id/name/spec/category_path
            vector_dim: 向量维度（默认 512，TF-IDF 特征数上限）
        """
        self.dict_rows = dict_rows or []
        self.vector_dim = vector_dim
        self._index: Optional['faiss.IndexFlatIP'] = None
        self._vectorizer = None
        self._id_to_row: dict[int, dict] = {}
        self._build_index()

    def _build_index(self):
        """构建 FAISS 索引。"""
        if not FAISS_AVAILABLE or not self.dict_rows:
            return

        from sklearn.feature_extraction.text import TfidfVectorizer

        # 构建文档
        docs = [
            _build_doc(
                row.get('name', ''),
                row.get('spec', ''),
                row.get('category_path', ''),
            )
            for row in self.dict_rows
        ]

        # TF-IDF 向量化
        self._vectorizer = TfidfVectorizer(
            tokenizer=_tokenize,
            token_pattern=None,
            max_features=self.vector_dim,
            ngram_range=(1, 2),
        )
        tfidf_matrix = self._vectorizer.fit_transform(docs)

        # 转换为 numpy 数组并归一化（L2 归一化，内积 = 余弦相似度）
        vectors = tfidf_matrix.toarray().astype('float32')
        actual_dim = vectors.shape[1]  # 实际特征数（可能小于 vector_dim）
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0  # 避免除零
        vectors = vectors / norms

        # 构建 FAISS 内积索引（归一化后内积 = 余弦相似度）
        # 使用实际特征数，而非固定的 vector_dim
        self._index = faiss.IndexFlatIP(actual_dim)
        self._index.add(vectors)

        # 建立 id 到 row 的映射
        for i, row in enumerate(self.dict_rows):
            self._id_to_row[i] = row

    def match(self, query_name: str, query_spec: str, top_n: int = 5) -> list[dict]:
        """匹配查询。

        Args:
            query_name: 清单项名称
            query_spec: 清单项规格
            top_n: 返回 Top-N 候选

        Returns:
            候选列表，按相似度降序，每项含 dict_id/name/spec/score/category_path
        """
        if not FAISS_AVAILABLE or not self.dict_rows or self._index is None:
            return []

        query_doc = _build_doc(query_name, query_spec)
        if not query_doc.strip():
            return []

        # 向量化查询
        query_vec = self._vectorizer.transform([query_doc]).toarray().astype('float32')

        # L2 归一化
        norm = np.linalg.norm(query_vec, axis=1, keepdims=True)
        norm[norm == 0] = 1.0
        query_vec = query_vec / norm

        # FAISS 检索 Top-N
        k = min(top_n, len(self.dict_rows))
        if k <= 0:
            return []

        scores, indices = self._index.search(query_vec, k)

        results = []
        for i in range(k):
            idx = int(indices[0][i])
            score = float(scores[0][i]) * 100  # 归一化到 0-100
            if score <= 0 or idx < 0 or idx not in self._id_to_row:
                continue
            row = self._id_to_row[idx]
            results.append({
                'dict_id': row.get('id'),
                'name': row.get('name', ''),
                'spec': row.get('spec', ''),
                'score': round(score, 2),
                'category_path': row.get('category_path', ''),
            })

        return results


def match_with_faiss(
    query_name: str,
    query_spec: str,
    dict_rows: list[dict],
    top_n: int = 5,
) -> list[dict]:
    """便捷函数：一次性匹配（每次重新构建索引，适合小数据量）。

    大数据量请使用 FaissMatcher 类，复用索引。
    """
    matcher = FaissMatcher(dict_rows)
    return matcher.match(query_name, query_spec, top_n=top_n)


def fuse_three_algorithms(
    rapidfuzz_cands: list[dict],
    tfidf_cands: list[dict],
    faiss_cands: list[dict],
    rf_weight: float = 0.3,
    tf_weight: float = 0.35,
    faiss_weight: float = 0.35,
) -> list[dict]:
    """融合三种算法的匹配结果（加权平均）。

    Args:
        rapidfuzz_cands: rapidfuzz 候选列表
        tfidf_cands: TF-IDF 候选列表
        faiss_cands: FAISS 候选列表
        rf_weight: rapidfuzz 权重（精确匹配强）
        tf_weight: TF-IDF 权重（语义匹配强）
        faiss_weight: FAISS 权重（向量检索强，大数据量快）

    Returns:
        融合后的候选列表，按综合分数降序
    """
    # 按 dict_id 建立索引
    rf_map = {c['dict_id']: c for c in rapidfuzz_cands}
    tf_map = {c['dict_id']: c for c in tfidf_cands}
    faiss_map = {c['dict_id']: c for c in faiss_cands}

    # 合并所有 dict_id
    all_ids = set(rf_map.keys()) | set(tf_map.keys()) | set(faiss_map.keys())

    fused = []
    for dict_id in all_ids:
        rf_cand = rf_map.get(dict_id)
        tf_cand = tf_map.get(dict_id)
        faiss_cand = faiss_map.get(dict_id)

        rf_score = rf_cand['score'] if rf_cand else 0.0
        tf_score = tf_cand['score'] if tf_cand else 0.0
        faiss_score = faiss_cand['score'] if faiss_cand else 0.0

        # 计算有来源的算法数量和权重总和
        sources = []
        total_weight = 0.0
        if rf_cand:
            sources.append(('rf', rf_score, rf_weight))
            total_weight += rf_weight
        if tf_cand:
            sources.append(('tf', tf_score, tf_weight))
            total_weight += tf_weight
        if faiss_cand:
            sources.append(('faiss', faiss_score, faiss_weight))
            total_weight += faiss_weight

        if not sources:
            continue

        # 加权平均（按有来源的权重归一化）
        if total_weight > 0:
            combined = sum(score * weight for _, score, weight in sources) / total_weight
        else:
            combined = sum(score for _, score, _ in sources) / len(sources)

        # 取有来源的候选信息
        base = rf_cand or tf_cand or faiss_cand
        fused.append({
            'dict_id': dict_id,
            'name': base['name'],
            'spec': base['spec'],
            'score': round(combined, 2),
            'category_path': base.get('category_path', ''),
            'rf_score': rf_score,
            'tf_score': tf_score,
            'faiss_score': faiss_score,
        })

    fused.sort(key=lambda c: c['score'], reverse=True)
    return fused
