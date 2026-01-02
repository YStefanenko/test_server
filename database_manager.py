import sqlite3
import bcrypt
import argparse
import json


DB_NAME = 'database.db'

DEFAULT_STATS = {
    "units_destroyed": 0,
    "shortest_game": 3600,
    "minimal_casualties": 100,
    "dev_defeated": False,
    "campaign_completed": False,
    "campaign_progress": []
}

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            steam_id TEXT NULL,
            score INTEGER DEFAULT 1000,
            number_of_wins INTEGER DEFAULT 0,
            number_of_games INTEGER DEFAULT 0,
            last_active INTEGER,
            stats TEXT DEFAULT '{"units_destroyed": 0, "shortest_game": 3600, "minimal_casualties": 100, "dev_defeated": false, "campaign_completed": false, "campaign_progress": []}',
            email TEXT NULL,
            title TEXT DEFAULT NULL,
            money INTEGER DEFAULT 0,
            items TEXT DEFAULT '[]'
        )
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
    c.execute('SELECT username, score, money FROM users ORDER BY score DESC')
    users = c.fetchall()
    conn.close()

    for username, score, money in users:
        print(f"{username}: {score}   with {money}$")


def add_money(username, amount):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(
        'UPDATE users SET money = money + ? WHERE username = ?',
        (amount, username))
    conn.commit()
    conn.close()
    print(f"Money for '{username}' increased by {amount}.")


def clear_items(username):
    default_value = json.dumps([])
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(
        'UPDATE users SET items = ? WHERE username = ?',
        (default_value, username)
    )
    conn.commit()

    if c.rowcount == 0:
        print(f"No user found with username '{username}'.")
    else:
        print(f"Items for '{username}' reset to {default_value}.")

    conn.close()


# def reset_all_stats():
#     conn = sqlite3.connect(DB_NAME)
#     c = conn.cursor()
#
#     default_stats_json = json.dumps(DEFAULT_STATS)
#
#     c.execute('UPDATE users SET stats = ?', (default_stats_json,))
#     conn.commit()
#     conn.close()
#
#     print("All user stats have been reset to default.")


def update_user_field(username, field, value):
    ALLOWED_USER_COLUMNS = {
        "password_hash",
        "steam_id",
        "score",
        "number_of_wins",
        "number_of_games",
        "last_active",
        "stats",
        "email",
        "title",
        "money",
        "items",
    }
    if field not in ALLOWED_USER_COLUMNS:
        raise ValueError(f"Invalid field name: {field}")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    query = f"UPDATE users SET {field} = ? WHERE username = ?"
    c.execute(query, (value, username))  # None → NULL automatically

    conn.commit()
    conn.close()


def print_database():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # conn_old = sqlite3.connect('database_old.db')
    # c_old = conn_old.cursor()
    #
    # c_old.execute("SELECT * FROM users")
    # rows = c_old.fetchall()
    #
    # for row in rows:
    #     c.execute('INSERT INTO users (username, password_hash, steam_id, score, number_of_wins, number_of_games, last_active, stats, email, title, money, items) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (row[0], row[1], None, row[2], row[3], row[4], row[5], row[8], row[6], row[7], row[9], row[10]))
    # conn.commit()

    c.execute("SELECT * FROM users")
    rows = c.fetchall()
    columns = [desc[0] for desc in c.description]

    for row in rows:
        row_dict = dict(zip(columns, row))
        print(row_dict)



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

    # Add money
    parser_delete = subparsers.add_parser("give", help="Delete an existing user")
    parser_delete.add_argument("username", help="Username to to give")
    parser_delete.add_argument("money", help="Amount")

    # Clear items
    parser_delete = subparsers.add_parser("clear", help="Clear items")
    parser_delete.add_argument("username", help="Username to clear")

    # Change value
    parser_change = subparsers.add_parser("change", help="Add steam coloumn")
    parser_change.add_argument("username", help="Username")
    parser_change.add_argument("field", help="Field")
    parser_change.add_argument("value", help="Value")
    
    parser_print = subparsers.add_parser("print", help="Print database")





    args = parser.parse_args()

    if args.command == "add":
        add_user(args.username, args.password)
    elif args.command == "delete":
        delete_user(args.username)
    elif args.command == "changepw":
        change_password(args.username, args.new_password)
    elif args.command == "list":
        list_users()
    elif args.command == "give":
        add_money(args.username, args.money)
    elif args.command == "clear":
        clear_items(args.username)
    elif args.command == "change":
        update_user_field(args.username, args.field, args.value)
    elif args.command == "print":
        update_user_field()
    else:
        parser.print_help()


# Convert to JSON string
default_json = json.dumps(DEFAULT_STATS)

main()
# init_db()
# copy()
