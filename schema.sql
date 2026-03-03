PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schedule (
  weekday INTEGER PRIMARY KEY CHECK(weekday BETWEEN 0 AND 6),
  is_open INTEGER NOT NULL DEFAULT 1 CHECK(is_open IN (0, 1)),
  start_time TEXT NOT NULL DEFAULT '18:00',
  end_time TEXT NOT NULL DEFAULT '19:20',
  max_seats INTEGER NOT NULL DEFAULT 20 CHECK(max_seats >= 0)
);

CREATE TABLE IF NOT EXISTS bookings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  booking_date TEXT NOT NULL, -- YYYY-MM-DD
  created_at TEXT NOT NULL,   -- ISO timestamp
  student_name TEXT NOT NULL,
  parent_name TEXT NOT NULL,
  group_number TEXT,
  parent_phone TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bookings_date ON bookings(booking_date);
