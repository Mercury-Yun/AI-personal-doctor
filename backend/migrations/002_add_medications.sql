CREATE TABLE IF NOT EXISTS medications (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  dosage TEXT,
  frequency TEXT,
  take_time TEXT,
  note TEXT,
  created_at DATETIME,
  FOREIGN KEY(user_id) REFERENCES users(id)
);
