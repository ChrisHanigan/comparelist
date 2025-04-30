DROP TABLE IF EXISTS items;
CREATE TABLE items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    rank INTEGER  -- Changed to allow NULL values
);
DROP TABLE IF EXISTS comparisons;
CREATE TABLE comparisons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item1_id INTEGER NOT NULL,
    item2_id INTEGER NOT NULL,
    score INTEGER NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (item1_id) REFERENCES items(id),
    FOREIGN KEY (item2_id) REFERENCES items(id),
    UNIQUE (item1_id, item2_id)
);
