-- Schema for Faisal Hills AI Lead Desk Verified Facts Database

CREATE TABLE IF NOT EXISTS fact_sources (
    source_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    document_name TEXT NOT NULL,
    document_date TEXT,
    uploaded_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    notes TEXT
);

CREATE TABLE IF NOT EXISTS society_master (
    fact_id TEXT PRIMARY KEY,
    society_name TEXT NOT NULL,
    location TEXT,
    developer TEXT,
    total_area TEXT,
    value TEXT NOT NULL,
    currency TEXT DEFAULT 'PKR',
    source_id TEXT NOT NULL,
    verified_by TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    demo INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (source_id) REFERENCES fact_sources(source_id)
);

CREATE TABLE IF NOT EXISTS blocks (
    fact_id TEXT PRIMARY KEY,
    block_name TEXT NOT NULL,
    status TEXT,
    features TEXT,
    value TEXT NOT NULL,
    currency TEXT DEFAULT 'PKR',
    source_id TEXT NOT NULL,
    verified_by TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    demo INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (source_id) REFERENCES fact_sources(source_id)
);

CREATE TABLE IF NOT EXISTS inventory (
    fact_id TEXT PRIMARY KEY,
    plot_id TEXT UNIQUE NOT NULL,
    block_name TEXT NOT NULL,
    size_marla REAL NOT NULL,
    category TEXT,
    status TEXT NOT NULL,
    value TEXT NOT NULL,
    currency TEXT DEFAULT 'PKR',
    source_id TEXT NOT NULL,
    verified_by TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    demo INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (source_id) REFERENCES fact_sources(source_id)
);

CREATE TABLE IF NOT EXISTS pricing (
    fact_id TEXT PRIMARY KEY,
    inventory_id TEXT,
    block_name TEXT,
    size_marla REAL,
    plot_type TEXT,
    price_pkr REAL NOT NULL,
    value TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'PKR',
    source_id TEXT NOT NULL,
    verified_by TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    demo INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (source_id) REFERENCES fact_sources(source_id)
);

CREATE TABLE IF NOT EXISTS payment_plans (
    fact_id TEXT PRIMARY KEY,
    plan_name TEXT NOT NULL,
    block_name TEXT,
    size_marla REAL,
    down_payment_pkr REAL,
    installment_amount_pkr REAL,
    total_months INTEGER,
    value TEXT NOT NULL,
    currency TEXT DEFAULT 'PKR',
    source_id TEXT NOT NULL,
    verified_by TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    demo INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (source_id) REFERENCES fact_sources(source_id)
);

CREATE TABLE IF NOT EXISTS legal_facts (
    fact_id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    approval_body TEXT,
    noc_status TEXT,
    statement TEXT NOT NULL,
    value TEXT NOT NULL,
    currency TEXT DEFAULT 'PKR',
    source_id TEXT NOT NULL,
    verified_by TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    demo INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (source_id) REFERENCES fact_sources(source_id)
);

CREATE TABLE IF NOT EXISTS faqs (
    fact_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    value TEXT NOT NULL,
    currency TEXT DEFAULT 'PKR',
    source_id TEXT NOT NULL,
    verified_by TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    demo INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (source_id) REFERENCES fact_sources(source_id)
);

CREATE TABLE IF NOT EXISTS leads (
    lead_id TEXT PRIMARY KEY,
    channel TEXT,
    phone_hash TEXT,
    language TEXT,
    lead_type TEXT,
    high_intent INTEGER DEFAULT 0,
    needs_human INTEGER DEFAULT 0,
    assigned_agent TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_log (
    audit_id INTEGER PRIMARY KEY,
    lead_id TEXT,
    step TEXT NOT NULL,
    input_text TEXT,
    output_text TEXT,
    decision_payload TEXT,
    fact_ids_used TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Customer messages handled by the pipeline.
-- M4 (D-20): app/pipeline.py inserts into `messages` on every handled
-- message, but this table was missing from the schema, so a database
-- built from schema.sql alone failed with "no such table: messages".
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id TEXT,
    message_text TEXT,
    message_timestamp TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Market Intelligence Listings (Scrubbed WhatsApp Dealer Chat Posts)
CREATE TABLE IF NOT EXISTS market_listings (
    listing_id INTEGER PRIMARY KEY,
    dedupe_hash TEXT UNIQUE NOT NULL,
    sender TEXT NOT NULL,
    raw_timestamp TEXT,
    block_code TEXT,
    size_marla REAL,
    category TEXT,
    side TEXT NOT NULL,  -- 'BUY' | 'SELL' | 'INQUIRY'
    price_pkr INTEGER,
    plot_no TEXT,
    is_corner INTEGER DEFAULT 0,
    is_boulevard INTEGER DEFAULT 0,
    is_park_facing INTEGER DEFAULT 0,
    ndc_open INTEGER DEFAULT 0,
    corner INTEGER DEFAULT 0,
    mdr INTEGER DEFAULT 0,
    solid INTEGER DEFAULT 0,
    sunface INTEGER DEFAULT 0,
    park_face INTEGER DEFAULT 0,
    pair INTEGER DEFAULT 0,
    dimension_raw TEXT,
    label_raw TEXT,
    attributes TEXT,
    raw_text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Market Intelligence Aggregate Statistics
CREATE TABLE IF NOT EXISTS market_stats (
    stat_id INTEGER PRIMARY KEY,
    block_code TEXT NOT NULL,
    size_marla REAL NOT NULL,
    side TEXT NOT NULL,  -- 'BUY' | 'SELL'
    sample_count INTEGER NOT NULL,
    min_price_pkr INTEGER NOT NULL,
    p25_price_pkr INTEGER NOT NULL,
    median_price_pkr INTEGER NOT NULL,
    p75_price_pkr INTEGER NOT NULL,
    max_price_pkr INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(block_code, size_marla, side)
);
