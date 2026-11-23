# TASK 08: Demo data and run modes

Follow PROJECT_STATE.md HARD RULES. Read PROGRESS.md, TASK_06.md and its amendment. Standard library plus pytest only. UTF-8 without BOM. Do not modify read-only files.

1. tools/make_fake_chat.py (seeded, deterministic): writes data/raw_chats/demo__fake_android.txt (about 400 lines, Android export format) and demo__fake_iphone.txt (iPhone format). Everything is FABRICATED: fake sender names "Dealer 01" etc, fake phone numbers like 0300-0000001. Listings in English, Roman Urdu and Urdu script for sizes 5 marla, 10 marla and 1 kanal, using demo block names DEMO_BLOCK_A, DEMO_BLOCK_B, DEMO_EXEC from market/blocks_demo.json; features corner or middle, facing, NDC open or not open, possession, developed; clearly fake price levels. Include noise: greetings, system lines, "<Media omitted>", multi-line messages, the same plot posted in two files, a few outlier prices, phone numbers that must be scrubbed.
2. config.py: APP_MODE env, demo or pilot (default pilot). In demo mode every market stat, fact, reply and API response carries demo=true. In pilot mode the pipeline MUST refuse (escalate) to use any stat or fact with demo=1 or a source_id starting with "demo_".
3. market/blocks_demo.json for demo blocks. The real market/blocks.json stays for the human to fill. The loader picks the file by APP_MODE.
4. tools/ingest_all.py: parse, scrub, extract, dedupe, store and compute stats for every .txt in data/raw_chats/ (demo files only in demo mode, no demo files in pilot mode). The tool defaults to pilot mode (APP_MODE=pilot) but can be overridden by setting the APP_MODE environment variable. Idempotent: re-running does not duplicate rows. Prints the market report.
5. tools/purge_demo.py: deletes all demo rows and demo files after confirmation.
6. Tests: pilot mode never uses demo stats; demo mode flags everything; ingest is idempotent; no phone number appears in the database.

Finish by listing exact commands to generate the fake chats, ingest, and run tests.
