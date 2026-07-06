CREATE TABLE IF NOT EXISTS chat_history (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at DATETIME,
  FOREIGN KEY(user_id) REFERENCES users(id)
);
