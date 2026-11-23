

# TASK 01: Verified-facts database (SQLite)

Follow PROJECT_STATE.md HARD RULES. Do not modify integration_test.py, controlled_gateway.py or shadow_mode.py.
Use only the Python standard library plus pytest. Save all files as UTF-8 without BOM.

Create:
1. data/schema.sql with SQLite tables: society_master, blocks, inventory, pricing, payment_plans, legal_facts, faqs, fact_sources, leads, audit_log.
   Every fact row must have: fact_id (unique text), value, currency (PKR for prices), source_id, verified_by, verified_at, valid_until, demo (0 or 1).
2. data/db.py with init_db(path) and a loader that REJECTS rows with: missing source_id/verified_by/verified_at/valid_until, an expired valid_until, duplicate inventory IDs, or a price that is not a positive number.
3. data/demo_seed.py that inserts about 10 clearly flagged demo rows (demo=1), e.g. 5 marla and 10 marla plots in two blocks.
4. tests/test_data_quality.py with pytest tests for every rejection rule above.

Finish by telling me the exact commands to run the tests.