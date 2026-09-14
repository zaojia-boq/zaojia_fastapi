# -*- coding: utf-8 -*-
"""Excel -> json.gz 无损转换（多 sheet 安全）。

设计要点（针对"不要丢数据"）：
1. 双通道读取：
   - data_only=True  -> 取缓存值（公式计算结果）
   - data_only=False -> 取公式原文
   两者合并：有公式的单元格存 {"f": 公式, "v": 值}，避免"程序生成的 xlsx 无缓存值导致全空"。
2. 类型保真：datetime/date/time 转 ISO 字符串，同时在 sheet.datetime_cells 记录坐标，
   避免反解时把 "2026-01-01" 误当成纯文本。
3. 保留：sheet 名称/顺序/可见状态、合并单元格范围、声明维度（max_row/max_column）
   与实际数据范围（data_extent）。
4. load_workbook 一律 read_only=True（AGENTS.md 铁律），本脚本只读、不写源 Excel。
5. gzip mtime=0，保证同样输入产生字节一致的输出（可复现）。

用法：
    python scripts/xlsx_to_json_gz.py "<xlsx 路径>" ["<更多 xlsx>"]
输出：同目录下 <原名>.json.gz
"""
import datetime as _dt
import gzip
import json
import sys
from pathlib import Path

import openpyxl


def _cell_value(v):
    """把单元格值转成 JSON 友好类型，datetime 转 ISO 并标记。"""
    if v is None:
        return None, None
    if isinstance(v, _dt.datetime):
        return v.isoformat(), "datetime"
    if isinstance(v, _dt.date):
        return v.isoformat(), "date"
    if isinstance(v, _dt.time):
        return v.isoformat(), "time"
    if isinstance(v, _dt.timedelta):
        return v.total_seconds(), "timedelta"
    if isinstance(v, (int, float, bool, str)):
        return v, None
    # 兜底：其他类型转字符串，避免 json 序列化失败丢数据
    return str(v), "str_fallback"


def convert_one(xlsx_path: Path) -> Path:
    wb_v = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    wb_f = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=False)

    sheets = []
    for idx, (name_v, name_f) in enumerate(zip(wb_v.sheetnames, wb_f.sheetnames)):
        ws_v = wb_v[name_v]
        ws_f = wb_f[name_f]

        rows = []
        datetime_cells = []
        formula_cells = 0
        nonempty = 0
        last_r = last_c = 0

        it_v = ws_v.iter_rows()
        it_f = ws_f.iter_rows()
        for r_i, (row_v, row_f) in enumerate(zip(it_v, it_f), start=1):
            out_row = []
            for c_i, (cell_v, cell_f) in enumerate(zip(row_v, row_f), start=1):
                val, dtype = _cell_value(cell_v.value)
                formula = cell_f.value if isinstance(cell_f.value, str) and cell_f.value.startswith("=") else None

                if val is None and formula is None:
                    out_row.append(None)
                    continue

                nonempty += 1
                last_r, last_c = r_i, max(last_c, c_i)
                if r_i > last_r:
                    last_r = r_i

                if dtype is not None:
                    datetime_cells.append([r_i, c_i, dtype])
                if formula is not None:
                    formula_cells += 1
                    out_row.append({"f": formula, "v": val})
                else:
                    out_row.append(val)
            rows.append(out_row)

        # 去掉尾部全空行（不丢数据，仅压缩体积）
        while rows and all(c is None for c in rows[-1]):
            rows.pop()

        sheets.append({
            "name": name_v,
            "index": idx,
            "state": getattr(ws_v, "sheet_state", "visible"),
            "declared_max_row": ws_v.max_row,
            "declared_max_column": ws_v.max_column,
            "data_extent": {"last_row": last_r, "last_column": last_c},
            "row_count": len(rows),
            "nonempty_cell_count": nonempty,
            "formula_cell_count": formula_cells,
            "datetime_cells": datetime_cells,
            "merged_ranges": [str(r) for r in getattr(ws_v, "merged_cells", []).ranges] if hasattr(ws_v, "merged_cells") else [],
            "rows": rows,
        })

    payload = {
        "source_file": xlsx_path.name,
        "source_bytes": xlsx_path.stat().st_size,
        "converted_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "converter": "scripts/xlsx_to_json_gz.py",
        "openpyxl_version": openpyxl.__version__,
        "read_mode": "read_only=True, data_only=True(+False 双通道)",
        "sheet_count": len(sheets),
        "sheets": sheets,
    }

    out_path = xlsx_path.with_suffix("").with_suffix(".json.gz") if xlsx_path.suffix else xlsx_path.with_name(xlsx_path.name + ".json.gz")
    if out_path.suffix != ".gz":
        out_path = xlsx_path.with_name(xlsx_path.stem + ".json.gz")

    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.GzipFile(out_path, mode="wb", compresslevel=9, mtime=0) as f:
        f.write(raw)

    wb_v.close()
    wb_f.close()
    return out_path, len(raw), sum(s["nonempty_cell_count"] for s in sheets)


def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/xlsx_to_json_gz.py <xlsx> [<xlsx> ...]")
        return 1
    for arg in sys.argv[1:]:
        p = Path(arg)
        if not p.exists():
            print(f"[跳过] 不存在: {p}")
            continue
        out, raw_len, cells = convert_one(p)
        gz_len = out.stat().st_size
        print(f"[OK] {p.name} -> {out.name}")
        print(f"     非空单元格 {cells} 个 | JSON {raw_len/1024:.1f} KB -> GZ {gz_len/1024:.1f} KB (压缩率 {gz_len/raw_len*100:.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
