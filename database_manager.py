import sqlite3
import bcrypt
import argparse

DB_NAME = 'database.db'


def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            score INTEGER DEFAULT 1000,
            number_of_wins INTEGER DEFAULT 0,
            number_of_games INTEGER DEFAULT 0,
            units_destroyed INTEGER DEFAULT 0,
            shortest_game INTEGER DEFAULT 3600,
            last_active INTEGER,
            email TEXT UNIQUE,
            title TEXT default NULL)
    ''')
    conn.commit()
    conn.close()


def add_user(username, password):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
    try:
        c.execute('INSERT INTO users (username, password_hash, score) VALUES (?, ?, ?)',
                  (username, password_hash, 0))
        conn.commit()
        print(f"User '{username}' added.")
    except sqlite3.IntegrityError:
        print(f"User '{username}' already exists.")
    finally:
        conn.close()


def delete_user(username):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('DELETE FROM users WHERE username = ?', (username,))
    conn.commit()
    conn.close()
    print(f"User '{username}' deleted.")


def change_password(username, new_password):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    c.execute('UPDATE users SET password_hash = ? WHERE username = ?', (new_hash, username))
    conn.commit()
    conn.close()
    print(f"Password for '{username}' updated.")


def list_users():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT username, score FROM users')
    users = c.fetchall()
    conn.close()
    for username, score in users:
        print(f"{username}: {score}")


def main():
    parser = argparse.ArgumentParser(description="User database manager")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Add user
    parser_add = subparsers.add_parser("add", help="Add a new user")
    parser_add.add_argument("username", help="Username to add")
    parser_add.add_argument("password", help="Password for the new user")

    # Delete user
    parser_delete = subparsers.add_parser("delete", help="Delete an existing user")
    parser_delete.add_argument("username", help="Username to delete")

    # Change password
    parser_changepw = subparsers.add_parser("changepw", help="Change a user's password")
    parser_changepw.add_argument("username", help="Username")
    parser_changepw.add_argument("new_password", help="New password")

    # List users
    subparsers.add_parser("list", help="List all users")

    args = parser.parse_args()

    if args.command == "add":
        add_user(args.username, args.password)
    elif args.command == "delete":
        delete_user(args.username)
    elif args.command == "changepw":
        change_password(args.username, args.new_password)
    elif args.command == "list":
        list_users()
    else:
        parser.print_help()

def drop_columns(db_path, table_name, drop_cols):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Get current schema
    cur.execute(f"PRAGMA table_info({table_name});")
    cols_info = cur.fetchall()
    all_cols = [col[1] for col in cols_info]

    # Keep only the columns not being dropped
    keep_cols = [c for c in all_cols if c not in drop_cols]

    # Build new schema
    col_defs = []
    for cid, name, col_type, notnull, dflt_value, pk in cols_info:
        if name in keep_cols:
            col_def = f"{name} {col_type}"
            if pk: col_def += " PRIMARY KEY"
            if notnull: col_def += " NOT NULL"
            if dflt_value is not None: col_def += f" DEFAULT {dflt_value}"
            col_defs.append(col_def)

    col_defs_str = ", ".join(col_defs)

    # Migration
    cur.execute("PRAGMA foreign_keys=off;")
    conn.commit()
    cur.execute("BEGIN TRANSACTION;")

    # Rename old table
    cur.execute(f"ALTER TABLE {table_name} RENAME TO {table_name}_old;")

    # Create new table without dropped columns
    cur.execute(f"CREATE TABLE {table_name} ({col_defs_str});")

    # Copy over data (only kept columns)
    keep_cols_str = ", ".join(keep_cols)
    cur.execute(f"""
        INSERT INTO {table_name} ({keep_cols_str})
        SELECT {keep_cols_str} FROM {table_name}_old;
    """)

    # Drop old table
    cur.execute(f"DROP TABLE {table_name}_old;")

    cur.execute("COMMIT;")
    cur.execute("PRAGMA foreign_keys=on;")
    conn.commit()
    conn.close()


drop_columns(DB_NAME, "users", ["units_destroyed", "shortest_game"])
