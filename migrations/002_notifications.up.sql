CREATE TABLE notifications (
    id                 INTEGER PRIMARY KEY,
    sent_at            TIMESTAMP NOT NULL,
    tier               INTEGER NOT NULL CHECK (tier IN (1, 2, 3)),
    event_type         TEXT    NOT NULL,
    vin                TEXT,
    title              TEXT    NOT NULL,
    body               TEXT    NOT NULL,
    url                TEXT,
    pushover_priority  INTEGER NOT NULL,
    pushover_response  TEXT,
    success            INTEGER NOT NULL DEFAULT 0 CHECK (success IN (0, 1))
);

CREATE INDEX notifications_recent ON notifications (sent_at DESC);
