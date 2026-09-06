# -*- coding: utf-8 -*-
"""zaojia_boq.data —— 纯函数数据层（FastAPI 版沿用 Odoo 版契约）。

本目录下的模块**不依赖任何框架**；pure_tests 经 importlib 按文件直接加载
（spec_from_file_location 指向 ../data/<name>.py），保证各模块可独立被测试。

职责边界（硬）——各文件功能单一，模块间互不交叉 import：
- field_spec.py       ：A/B/C 字段分层定义（数据安全根基，单一事实源，带 isdisjoint 自检）；
- aliases.py          ：Excel 表头「列名 → 规范字段」映射 + extract_field_value 首个非空列回退；
- gb_code.py          ：国标清单编码解析 parse_gb_code + 同类项聚合键 compute_match_key；
- unit_normalize.py   ：计量单位归一化（米/m/M → m 等）；
- match_score.py      ：物料匹配纯评分（rapidfuzz）score_candidates + high_confidence；
- price_calc.py       ：综合单价/合价计算与校验；
- quality_metrics.py  ：数据质量指标 compute_metrics + m3/m4 达标门（自含门槛常量）；
- cost_catalog_gate.py：定额成本库门槛判定（本地重定义 M4 阈值，一致性由 pure_tests 守卫）。

约定：本层不反向依赖 app/ 的 model/service；M1 业务层只「调用」本层、不「改写」。
"""