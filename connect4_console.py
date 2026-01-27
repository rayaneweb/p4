import random

EMPTY = "."
RED = "R"
YELLOW = "Y"

def create_board(rows, cols):
    return [[EMPTY for _ in range(cols)] for _ in range(rows)]

def drop_token(board, col, token):
    rows = len(board)
    cols = len(board[0])

    if col < 0 or col >= cols:
        return None
    if board[0][col] != EMPTY:
        return None

    for r in range(rows - 1, -1, -1):
        if board[r][col] == EMPTY:
            board[r][col] = token
            return (r, col)
    return None

def robot_random_column(board):
    valid = [c for c in range(len(board[0])) if board[0][c] == EMPTY]
    return random.choice(valid) if valid else None

def is_human_turn(mode, current):
    if mode == 2:
        return True
    if mode == 0:
        return False
    return current == RED
