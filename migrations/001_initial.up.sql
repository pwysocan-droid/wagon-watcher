CREATE TABLE listings (
    vin                 TEXT    PRIMARY KEY,
    first_seen          TIMESTAMP NOT NULL,
    last_seen           TIMESTAMP NOT NULL,
    status              TEXT    NOT NULL CHECK (status IN ('active', 'gone', 'reappeared')),
    gone_at             TIMESTAMP,
    dealer_name         TEXT,
    dealer_zip          TEXT,
    dealer_state        TEXT,
    year                INTEGER,
    model               TEXT,
    trim                TEXT,
    body_style          TEXT,
    exterior_color      TEXT,
    interior_color      TEXT,
    mileage_first_seen  INTEGER,
    photo_url           TEXT,
    listing_url         TEXT,
    options_json        TEXT,
    vin_decode_json     TEXT
);

CREATE TABLE price_history (
    id           INTEGER PRIMARY KEY,
    vin          TEXT    NOT NULL REFERENCES listings(vin),
    observed_at  TIMESTAMP NOT NULL,
    price        INTEGER NOT NULL,
    mileage      INTEGER NOT NULL
);

CREATE INDEX idx_price_history_vin_observed ON price_history(vin, observed_at);

CREATE TABLE notes (
    id          INTEGER PRIMARY KEY,
    vin         TEXT    NOT NULL,
    created_at  TIMESTAMP NOT NULL,
    note        TEXT    NOT NULL,
    tags        TEXT
);

CREATE TABLE runs (
    id                INTEGER PRIMARY KEY,
    started_at        TIMESTAMP NOT NULL,
    finished_at       TIMESTAMP,
    listings_found    INTEGER,
    new_count         INTEGER,
    changed_count     INTEGER,
    gone_count        INTEGER,
    reappeared_count  INTEGER,
    duration_ms       INTEGER,
    status            TEXT NOT NULL CHECK (status IN ('ok', 'aborted', 'error')),
    error_message     TEXT
);

CREATE TABLE watchlist (
    id          INTEGER PRIMARY KEY,
    kind        TEXT    NOT NULL CHECK (kind IN ('vin', 'spec')),
    vin         TEXT,
    spec_json   TEXT,
    label       TEXT,
    created_at  TIMESTAMP NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);
