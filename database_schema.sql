-- =======================
-- BASE DE DONNÉES PUISSANCE 4
-- =======================

-- Extension nécessaire pour digest()
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Table des utilisateurs
CREATE TABLE IF NOT EXISTS users (
    user_id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table des parties
CREATE TABLE IF NOT EXISTS games (
    game_id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    game_index INTEGER NOT NULL,
    rows_count INTEGER NOT NULL CHECK (rows_count BETWEEN 4 AND 20),
    cols_count INTEGER NOT NULL CHECK (cols_count BETWEEN 4 AND 20),
    starting_color CHAR(1) CHECK (starting_color IN ('R', 'Y')),
    ai_mode VARCHAR(20) DEFAULT 'random',
    ai_depth INTEGER DEFAULT 4 CHECK (ai_depth BETWEEN 1 AND 8),
    game_mode INTEGER CHECK (game_mode IN (0, 1, 2)),
    status VARCHAR(20) DEFAULT 'in_progress'
        CHECK (status IN ('in_progress', 'completed', 'aborted')),
    winner CHAR(1) CHECK (winner IN ('R', 'Y', 'D')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    board_hash VARCHAR(64) UNIQUE,
    moves_hash VARCHAR(64) UNIQUE
);

-- Table des coups
CREATE TABLE IF NOT EXISTS moves (
    move_id SERIAL PRIMARY KEY,
    game_id INTEGER REFERENCES games(game_id) ON DELETE CASCADE,
    move_index INTEGER NOT NULL,
    column_played INTEGER NOT NULL CHECK (column_played >= 0),
    player CHAR(1) CHECK (player IN ('R', 'Y')),
    board_state TEXT,
    evaluation_score INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (game_id, move_index)
);

-- Table des positions
CREATE TABLE IF NOT EXISTS positions (
    position_id SERIAL PRIMARY KEY,
    board_hash VARCHAR(64) UNIQUE NOT NULL,
    board_state TEXT NOT NULL,
    rows_count INTEGER NOT NULL,
    cols_count INTEGER NOT NULL,
    next_player CHAR(1) CHECK (next_player IN ('R', 'Y')),
    terminal BOOLEAN DEFAULT FALSE,
    winner CHAR(1) CHECK (winner IN ('R', 'Y', 'D')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index (PostgreSQL correct)
CREATE INDEX IF NOT EXISTS idx_board_hash ON positions(board_hash);
CREATE INDEX IF NOT EXISTS idx_terminal ON positions(terminal);

-- Table de liaison parties-positions
CREATE TABLE IF NOT EXISTS game_positions (
    game_id INTEGER REFERENCES games(game_id) ON DELETE CASCADE,
    position_id INTEGER REFERENCES positions(position_id) ON DELETE CASCADE,
    move_index INTEGER NOT NULL,
    PRIMARY KEY (game_id, position_id)
);

-- Table des symétries
CREATE TABLE IF NOT EXISTS symmetries (
    symmetry_id SERIAL PRIMARY KEY,
    original_position_id INTEGER REFERENCES positions(position_id),
    symmetric_position_id INTEGER REFERENCES positions(position_id),
    symmetry_type VARCHAR(20)
        CHECK (symmetry_type IN (
            'horizontal', 'vertical',
            'rotate180', 'rotate90', 'rotate270'
        )),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (original_position_id, symmetric_position_id, symmetry_type)
);

-- Statistiques des positions
CREATE TABLE IF NOT EXISTS position_stats (
    position_id INTEGER PRIMARY KEY REFERENCES positions(position_id),
    times_played INTEGER DEFAULT 0,
    red_wins INTEGER DEFAULT 0,
    yellow_wins INTEGER DEFAULT 0,
    draws INTEGER DEFAULT 0,
    avg_evaluation_score FLOAT,
    last_played TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table des parties sauvegardées (simplifiée pour game.py)
CREATE TABLE IF NOT EXISTS saved_games (
    id SERIAL PRIMARY KEY,
    save_name VARCHAR(100) NOT NULL,
    save_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    rows INTEGER NOT NULL,
    cols INTEGER NOT NULL,
    starting_color CHAR(1) NOT NULL,
    mode INTEGER NOT NULL,
    game_index INTEGER NOT NULL,
    moves JSONB NOT NULL,
    view_index INTEGER NOT NULL,
    ai_mode VARCHAR(20) NOT NULL,
    ai_depth INTEGER NOT NULL
);

-- Vue d'analyse des parties
CREATE OR REPLACE VIEW game_details AS
SELECT
    g.game_id,
    g.game_index,
    g.rows_count,
    g.cols_count,
    g.starting_color,
    g.ai_mode,
    g.ai_depth,
    g.game_mode,
    g.status,
    g.winner,
    g.created_at,
    g.completed_at,
    COUNT(m.move_id) AS total_moves,
    u.username
FROM games g
LEFT JOIN moves m ON g.game_id = m.game_id
LEFT JOIN users u ON g.user_id = u.user_id
GROUP BY g.game_id, u.username;

-- Fonction de hachage du plateau
CREATE OR REPLACE FUNCTION calculate_board_hash(board_state TEXT)
RETURNS VARCHAR(64) AS $$
BEGIN
    RETURN encode(digest(board_state, 'sha256'), 'hex');
END;
$$ LANGUAGE plpgsql;
