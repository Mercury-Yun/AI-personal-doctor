CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  age INTEGER,
  gender TEXT,
  height REAL,
  weight REAL,
  phone TEXT,
  emergency_contact TEXT,
  emergency_phone TEXT,
  allergy TEXT,
  remark TEXT,
  created_at DATETIME
);

CREATE TABLE IF NOT EXISTS medical_records (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  chronic_disease TEXT,
  history TEXT,
  current_symptom TEXT,
  medicine TEXT,
  doctor_advice TEXT,
  created_at DATETIME,
  FOREIGN KEY(user_id) REFERENCES users(id)
);

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

CREATE TABLE IF NOT EXISTS chat_history (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  session_id INTEGER,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at DATETIME,
  FOREIGN KEY(session_id) REFERENCES chat_sessions(id),
  FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS chat_sessions (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  created_at DATETIME,
  updated_at DATETIME,
  FOREIGN KEY(user_id) REFERENCES users(id)
);
