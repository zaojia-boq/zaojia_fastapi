import psycopg2
conn = psycopg2.connect("postgresql://odoo@localhost:5432/zaojia_fastapi")
cur = conn.cursor()
cur.execute("SELECT id, name, level FROM material_dict WHERE name IN ('电箱', '配电') OR name LIKE '%电箱%' OR name LIKE '配电%'")
for r in cur.fetchall():
    print(r)
conn.close()
