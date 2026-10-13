CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    telegram_user_id INTEGER NOT NULL,
    title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
    deadline_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed')),
    created_at TEXT NOT NULL,
    completed_at TEXT,
    reminder_sent_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_user_status_deadline
    ON tasks (telegram_user_id, status, deadline_at);

CREATE INDEX IF NOT EXISTS idx_tasks_status_reminder_deadline
    ON tasks (status, reminder_sent_at, deadline_at);
