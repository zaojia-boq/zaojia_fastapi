# -*- coding: utf-8 -*-
"""ETL 迁移脚本：Odoo zaojia_db → FastAPI zaojia_fastapi。

迁移顺序（按外键依赖）：
1. material_dict（物料字典，无外键）
2. import_batch（导入批次，无外键）
3. boq_item（清单项，外键 → import_batch / material_dict）
4. audit_log（审计日志，软引用无外键）

三重校验：
1. 行数校验：原库行数 == 新库行数
2. B 类字段逐字段校验：std_name/std_spec/material_dict_id 等不可重建字段逐行比对
3. 校验和比对：checksum_count/checksum_total 与原库 import_batch 一致

使用方式：
    python scripts/migrate_odoo_to_fastapi.py
"""
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.models.material_dict import MaterialDict
from app.models.import_batch import ImportBatch
from app.models.boq_item import BoqItem
from app.models.audit_log import AuditLog

# 数据库连接
OLD_DB_URL = "postgresql+psycopg2://odoo@localhost:5432/zaojia_db"
NEW_DB_URL = "postgresql+psycopg2://odoo@localhost:5432/zaojia_fastapi"

# B 类字段（不可重建，需逐字段校验）
B_FIELDS = ['std_name', 'std_spec', 'material_dict_id']


def get_old_session():
    """原库 session（只读）。"""
    engine = create_engine(OLD_DB_URL, future=True)
    Session = sessionmaker(bind=engine, future=True)
    return Session()


def get_new_session():
    """新库 session。"""
    engine = create_engine(NEW_DB_URL, future=True)
    Session = sessionmaker(bind=engine, future=True)
    return Session(), engine


def create_new_tables(engine):
    """在新库中建表。"""
    Base.metadata.create_all(bind=engine)
    print("[1/5] 新库表结构创建完成")


def migrate_material_dict(old_db, new_db):
    """迁移物料字典。"""
    rows = old_db.execute(text("""
        SELECT id, biz_id, level, parent_id, name,
               cat_l1, cat_l2, cat_l3,
               synonyms, spec_whitelist, note,
               create_date, write_date
        FROM zaojia_material_dict
        ORDER BY id
    """)).fetchall()

    count = 0
    for row in rows:
        item = MaterialDict(
            id=row.id,
            biz_id=row.biz_id,
            level=row.level,
            parent_id=row.parent_id,
            name=row.name,
            cat_l1=row.cat_l1,
            cat_l2=row.cat_l2,
            cat_l3=row.cat_l3,
            synonyms=row.synonyms,
            spec_whitelist=row.spec_whitelist,
            note=row.note,
            create_date=row.create_date,
            write_date=row.write_date,
        )
        new_db.add(item)
        count += 1

    new_db.flush()
    print(f"[2/5] material_dict 迁移完成：{count} 行")
    return count


def migrate_import_batch(old_db, new_db):
    """迁移导入批次。"""
    rows = old_db.execute(text("""
        SELECT id, biz_id, name, source_file, file_hash, row_count,
               imported_count, skipped_count, anomaly_count, imported_at,
               province, price_period, operator, archive_path, source_path,
               checksum_count, checksum_total, checksum_hash,
               data_source_type, active, create_date, write_date
        FROM zaojia_import_batch
        ORDER BY id
    """)).fetchall()

    count = 0
    for row in rows:
        item = ImportBatch(
            id=row.id,
            biz_id=row.biz_id,
            name=row.name,
            source_file=row.source_file,
            file_hash=row.file_hash,
            row_count=row.row_count,
            imported_count=row.imported_count,
            skipped_count=row.skipped_count,
            anomaly_count=row.anomaly_count,
            imported_at=row.imported_at,
            province=row.province,
            price_period=row.price_period,
            operator=row.operator,
            archive_path=row.archive_path,
            source_path=row.source_path,
            checksum_count=row.checksum_count,
            checksum_total=row.checksum_total,
            checksum_hash=row.checksum_hash,
            data_source_type=row.data_source_type,
            active=row.active if row.active is not None else True,
            create_date=row.create_date,
            write_date=row.write_date,
        )
        new_db.add(item)
        count += 1

    new_db.flush()
    print(f"[3/5] import_batch 迁移完成：{count} 行")
    return count


def migrate_boq_item(old_db, new_db):
    """迁移清单项。"""
    rows = old_db.execute(text("""
        SELECT id, biz_id, import_batch_id, sequence, material_dict_id,
               project_name, sub_division, province, ordinal,
               item_code, item_code_raw, item_code_version,
               item_name, item_feature, unit, unit_std,
               quantity, unit_rate, total, provisional_sum,
               quantity_num, unit_rate_num, total_num, provisional_sum_num,
               std_name, std_spec, data_source_type,
               match_key, match_key_source, aggregate_id,
               anomaly_flag, anomaly_reason,
               source_path, source_sheet, price_period,
               active, orphaned, create_date, write_date
        FROM zaojia_boq_item
        ORDER BY id
    """)).fetchall()

    count = 0
    for row in rows:
        item = BoqItem(
            id=row.id,
            biz_id=row.biz_id,
            import_batch_id=row.import_batch_id,
            sequence=row.sequence,
            material_dict_id=row.material_dict_id,
            project_name=row.project_name,
            sub_division=row.sub_division,
            province=row.province,
            ordinal=row.ordinal,
            item_code=row.item_code,
            item_code_raw=row.item_code_raw,
            item_name=row.item_name,
            item_feature=row.item_feature,
            unit=row.unit,
            unit_std=row.unit_std,
            quantity=row.quantity,
            unit_rate=row.unit_rate,
            total=row.total,
            quantity_num=float(row.quantity_num) if row.quantity_num is not None else None,
            unit_rate_num=float(row.unit_rate_num) if row.unit_rate_num is not None else None,
            total_num=float(row.total_num) if row.total_num is not None else None,
            std_name=row.std_name,
            std_spec=row.std_spec,
            data_source_type=row.data_source_type,
            match_key=row.match_key,
            match_key_source=row.match_key_source,
            aggregate_id=row.aggregate_id,
            anomaly_flag=row.anomaly_flag,
            anomaly_reason=row.anomaly_reason,
            source_path=row.source_path,
            source_sheet=row.source_sheet,
            price_period=row.price_period,
            active=row.active if row.active is not None else True,
            orphaned=row.orphaned if row.orphaned is not None else False,
            create_date=row.create_date,
            write_date=row.write_date,
        )
        new_db.add(item)
        count += 1

    new_db.flush()
    print(f"[4/5] boq_item 迁移完成：{count} 行")
    return count


def migrate_audit_log(old_db, new_db):
    """迁移审计日志。

    原库用 user_id（Odoo 用户 ID），新库用 operator（用户名字符串）。
    简化处理：直接用 user_id 字符串作为 operator，避免 Odoo res_users/res_partner 关联复杂性。
    原库无 trace_id，迁移时设为 None。
    """
    rows = old_db.execute(text("""
        SELECT id, model, res_id, action, field_name,
               old_value, new_value, reason, timestamp,
               batch_id, user_id
        FROM zaojia_audit_log
        ORDER BY id
    """)).fetchall()

    count = 0
    for row in rows:
        operator = f"user_{row.user_id}" if row.user_id else "system"
        item = AuditLog(
            id=row.id,
            model=row.model,
            res_id=row.res_id,
            action=row.action,
            field_name=row.field_name,
            old_value=row.old_value,
            new_value=row.new_value,
            operator=operator,
            reason=row.reason,
            trace_id=None,  # 原库无 trace_id
            timestamp=row.timestamp,
            batch_id=row.batch_id,
        )
        new_db.add(item)
        count += 1

    new_db.flush()
    print(f"[5/5] audit_log 迁移完成：{count} 行")
    return count


def verify_row_counts(old_db, new_db):
    """校验1：行数校验。"""
    print("\n=== 三重校验 ===")
    tables = [
        ('material_dict', 'zaojia_material_dict', MaterialDict),
        ('import_batch', 'zaojia_import_batch', ImportBatch),
        ('boq_item', 'zaojia_boq_item', BoqItem),
        ('audit_log', 'zaojia_audit_log', AuditLog),
    ]

    all_pass = True
    for name, old_table, model in tables:
        old_count = old_db.execute(text(f"SELECT count(*) FROM {old_table}")).scalar()
        new_count = new_db.query(model).count()
        status = "✓" if old_count == new_count else "✗"
        if old_count != new_count:
            all_pass = False
        print(f"  {status} {name}: 原库 {old_count} → 新库 {new_count}")

    return all_pass


def verify_b_fields(old_db, new_db):
    """校验2：B 类字段逐字段校验（不可重建字段）。"""
    print("\n--- B 类字段逐字段校验 ---")
    old_rows = old_db.execute(text("""
        SELECT id, std_name, std_spec, material_dict_id
        FROM zaojia_boq_item
        WHERE std_name IS NOT NULL OR std_spec IS NOT NULL OR material_dict_id IS NOT NULL
        ORDER BY id
    """)).fetchall()

    mismatch = 0
    checked = 0
    for old in old_rows:
        new = new_db.get(BoqItem, old.id)
        if new is None:
            print(f"  ✗ id={old.id}: 新库不存在")
            mismatch += 1
            continue
        for field in B_FIELDS:
            old_val = getattr(old, field)
            new_val = getattr(new, field)
            if old_val != new_val:
                print(f"  ✗ id={old.id} {field}: 原={old_val!r} 新={new_val!r}")
                mismatch += 1
        checked += 1

    if mismatch == 0:
        print(f"  ✓ B 类字段全部一致（检查 {checked} 行，{len(B_FIELDS)} 字段/行）")
    return mismatch == 0


def verify_checksum(old_db, new_db):
    """校验3：批次校验和比对。"""
    print("\n--- 批次校验和比对 ---")
    old_batches = old_db.execute(text("""
        SELECT id, name, checksum_count, checksum_total, checksum_hash
        FROM zaojia_import_batch
        ORDER BY id
    """)).fetchall()

    mismatch = 0
    for old in old_batches:
        new = new_db.get(ImportBatch, old.id)
        if new is None:
            print(f"  ✗ batch id={old.id}: 新库不存在")
            mismatch += 1
            continue
        # checksum_count 和 checksum_total 比对
        if old.checksum_count != new.checksum_count:
            print(f"  ✗ batch {old.name}: checksum_count 原={old.checksum_count} 新={new.checksum_count}")
            mismatch += 1
        if old.checksum_total is not None and new.checksum_total is not None:
            if abs(float(old.checksum_total) - float(new.checksum_total)) > 0.01:
                print(f"  ✗ batch {old.name}: checksum_total 原={old.checksum_total} 新={new.checksum_total}")
                mismatch += 1

    if mismatch == 0:
        print(f"  ✓ 全部批次校验和一致（{len(old_batches)} 个批次）")
    return mismatch == 0


def main():
    print("=" * 60)
    print("ETL 迁移：Odoo zaojia_db → FastAPI zaojia_fastapi")
    print("=" * 60)

    old_db = get_old_session()
    new_db, new_engine = get_new_session()

    try:
        # 1. 建表
        create_new_tables(new_engine)

        # 2-5. 迁移（按依赖顺序）
        migrate_material_dict(old_db, new_db)
        migrate_import_batch(old_db, new_db)
        migrate_boq_item(old_db, new_db)
        migrate_audit_log(old_db, new_db)

        # 提交
        new_db.commit()
        print("\n数据提交完成")

        # 三重校验
        r1 = verify_row_counts(old_db, new_db)
        r2 = verify_b_fields(old_db, new_db)
        r3 = verify_checksum(old_db, new_db)

        print("\n" + "=" * 60)
        if r1 and r2 and r3:
            print("✓ 三重校验全部通过，迁移成功！")
        else:
            print("✗ 校验未全部通过，请检查上述差异")
        print("=" * 60)

    except Exception as e:
        new_db.rollback()
        print(f"\n✗ 迁移失败：{e}")
        raise
    finally:
        old_db.close()
        new_db.close()


if __name__ == "__main__":
    main()
