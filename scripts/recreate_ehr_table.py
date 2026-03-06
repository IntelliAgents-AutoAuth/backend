import sys
sys.path.insert(0, ".")

from db.session import engine
from sqlalchemy import text, inspect

# Drop old tables (all possible names)
with engine.connect() as conn:
    conn.execute(text('DROP TABLE IF EXISTS "case"'))
    conn.execute(text('DROP TABLE IF EXISTS "cases"'))
    conn.execute(text('DROP TABLE IF EXISTS "ehrs"'))
    conn.commit()
    print("Dropped old case/cases/ehrs tables")

# Recreate all tables from the current models
from db.base import Base
Base.metadata.create_all(bind=engine)

# Verify
insp = inspect(engine)
print("DB tables now:", insp.get_table_names())
for table in insp.get_table_names():
    cols = [c["name"] for c in insp.get_columns(table)]
    print(f"  {table} columns: {cols}")
