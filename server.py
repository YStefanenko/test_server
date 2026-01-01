import asyncio
import struct
import sqlite3
import bcrypt
import random
import time
import socket
from email.message import EmailMessage
import aiosmtplib
import os
import json
import orjson


online_users = set()
rooms = {}
database_name = 'database.db'
queue_1v1 = None
queue_v3 = None
queue_v4 = None
queue_v34 = None
online_users_lock = None
room_lock = None
pending_codes = {}
pending_codes_lock = None

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

DEFAULT_STATS = {
    "units_destroyed": 0,
    "shortest_game": 3600,
    "minimal_casualties": 100,
    "dev_defeated": False,
    "campaign_completed": False,
    "campaign_progress": []
}


class Player:
    def __init__(self, username, reader, writer, score):
        self.username = username
        self.reader = reader
        self.writer = writer
        self.score = score


# Everything needed to create a game room

class GameRoom:
    def __init__(self, code, mode, custom_map=None):
        self.code = code
        self.players = []
        self.mode = mode
        self.nplayers = 2 if self.mode == '1v1' else 3 if self.mode == 'v3' else 4

        self.ready = False

        if custom_map is None:
            self.custom_map = None
        else:
            self.custom_map = orjson.loads(custom_map)

    async def add_player(self, player):
        self.players.append(player)
        if not len(self.players) == 1:
            await send_orjson(player.writer, orjson.dumps({'mode': self.mode, 'map': self.custom_map, 'players': [self.players[i].username for i in range(len(self.players))]}))

        if len(self.players) >= self.nplayers:
            self.ready = True

    async def start(self):
        if len(self.players) > self.nplayers:
            spectators = self.players[self.nplayers:]
        else:
            spectators = None

        if self.mode == '1v1':
            asyncio.create_task(game_session('1v1', self.players[:self.nplayers], score=False, spectators=spectators))
        if self.mode == 'v3':
            asyncio.create_task(game_session('v3', self.players[:self.nplayers], score=False, spectators=spectators))
        if self.mode == 'v4':
            asyncio.create_task(game_session('v4', self.players[:self.nplayers], score=False, spectators=spectators))

        await delete_game_room(self.code)

    async def check_room(self):
        info = {'players': [self.players[i].username for i in range(len(self.players))]}
        for i in range(len(self.players) - 1, -1, -1):
            if i == 0:
                info['ready'] = self.ready
            response = await is_connected_vroom(self.players[i], info)
            if response:
                if i == 0:
                    if 'action' in response and response['action'] == 'start':
                        await self.start()
            else:
                await disconnect(self.players[i])
                self.players.remove(self.players[i])

                if len(self.players) >= self.nplayers:
                    self.ready = True
                else:
                    self.ready = False

        if not self.players:
            await delete_game_room(self.code)


async def create_game_room(code, room):
    async with room_lock:
        rooms[code] = room


async def delete_game_room(code):
    async with room_lock:
        del rooms[code]


async def room_exists(code):
    async with room_lock:
        return code in rooms


async def is_connected_vroom(player, info):
    try:
        info['action'] = 'check'
        if await send_orjson(player.writer, orjson.dumps(info)) == 0:
            return False

        response = await asyncio.wait_for(read_orjson(player.reader), timeout=1)

        return orjson.loads(response)

    except Exception as e:
        print(f"[ERROR] is_connected: {e}")
        return False


# Everything needed to create a new account

async def generate_password(len):
    characters = 'acdefghjkmnpqrtuvwxyzACDEFGHJKMNPQRTUVWXYZ234679'
    password = ''.join(random.choice(characters) for _ in range(len))
    return password


async def user_exists(username):
    def blocking_check():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()
        c.execute('SELECT 1 FROM users WHERE username = ?', (username,))
        result = c.fetchone()
        conn.close()
        return result is not None

    return await asyncio.to_thread(blocking_check)


async def email_exists(email):
    def blocking_check():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()
        c.execute('SELECT 1 FROM users WHERE email = ?', (email,))
        result = c.fetchone()
        conn.close()
        return result is not None

    return await asyncio.to_thread(blocking_check)


async def steam_id_exists(steam_id):
    def blocking_check():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()
        c.execute('SELECT 1 FROM users WHERE steam_id = ?', (steam_id,))
        result = c.fetchone()
        conn.close()
        return result is not None

    return await asyncio.to_thread(blocking_check)


async def check_if_active(username):
    def blocking_check():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()
        c.execute('SELECT last_active FROM users WHERE username = ?', (username,))
        result = c.fetchone()
        conn.close()

        if result is not None and result[0] is not None:
            last_active = float(result[0])
            return (time.time() - last_active) < 1798  # 30 minutes in seconds
        return False

    return await asyncio.to_thread(blocking_check)


async def add_user(username, password, email, steam_id):
    def blocking_add():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
        last_active = time.time()

        try:
            c.execute('''
                INSERT INTO users (
                    username, password_hash, last_active, email, steam_id
                ) VALUES (?, ?, ?, ?, ?)
            ''', (username, password_hash, last_active, email, steam_id))
            conn.commit()
            return 1
        except sqlite3.IntegrityError:
            return 0
        finally:
            conn.close()

    return await asyncio.to_thread(blocking_add)


async def delete_user(username):
    def blocking_delete():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()
        c.execute('DELETE FROM users WHERE username = ?', (username,))
        conn.commit()
        conn.close()

    await asyncio.to_thread(blocking_delete)


async def get_username(steam_id):
    def blocking_login():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()
        c.execute('SELECT username FROM users WHERE steam_id = ?', (steam_id,))
        result = c.fetchone()
        conn.close()

        return result[0] if result is not None else None

    result = await asyncio.to_thread(blocking_login)

    return result


async def add_steam_id(username, steam_id):
    def blocking_change():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()

        try:
            c.execute("UPDATE users SET steam_id = ? WHERE username = ?", (steam_id, username))
            conn.commit()
            return 1
        except sqlite3.IntegrityError:
            return 0
        finally:
            conn.close()

    return await asyncio.to_thread(blocking_change)



async def get_email_address(username):
    def blocking_login():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()
        c.execute('SELECT email FROM users WHERE username = ?', (username,))
        result = c.fetchone()
        conn.close()

        return result

    result = await asyncio.to_thread(blocking_login)

    return result


async def change_password(username, password):
    def blocking_change():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

        try:
            c.execute("UPDATE users SET password_hash = ? WHERE username = ?", (password_hash, username))
            conn.commit()
            return 1
        except sqlite3.IntegrityError:
            return 0
        finally:
            conn.close()

    return await asyncio.to_thread(blocking_change)


async def send_email(text, email):
    if not EMAIL_USER or not EMAIL_PASS:
        print("Environment variables EMAIL_USER or EMAIL_PASS are not set.")
        return 0

    message = EmailMessage()
    message["From"] = EMAIL_USER
    message["To"] = email
    message["Subject"] = "War of Dots"
    message.set_content(text)

    try:
        response = await aiosmtplib.send(
            message,
            hostname="smtp.gmail.com",
            port=587,
            start_tls=True,
            username=EMAIL_USER,
            password=EMAIL_PASS,
            timeout=10)
        print(f"Email sent: {response}")
        return 1
    except aiosmtplib.SMTPException as e:
        print(f"SMTP error occurred: {e}")
    except asyncio.TimeoutError:
        print("Email send timed out.")
    except Exception as e:
        print(f"Unexpected error: {e}")
    return 0


async def register_user(username, email, steam_id=None):
    status = 1 - await user_exists(username)
    if not status:
        return 0, 'username_taken'
    status = 1 - await email_exists(email)
    if not status:
        return 0, 'email_taken'
    generated_password = await generate_password(12)
    status = await add_user(username, generated_password, email, steam_id)
    if not status:
        return 0, 'username_taken'
    code = await generate_password(4)
    async with pending_codes_lock:
        pending_codes[username] = code
    status = await send_email(f"""
        Hi {username},

        Thank you for registering an account in War of Dots!

        Here is your verification code:        
        {code}
        You have 30 minutes to log in, otherwise the account will be deactivated.

        I am excited to have you in the battle. Thanks again, and enjoy the game!

        – TeaAndPython
    """, email)
    if not status:
        await delete_user(username)
        return 0, 'email_invalid'

    return 1, None


async def login1(username, email):
    status = await user_exists(username)
    if not status:
        return 0, 'user_does_not_exist'
    real_email = await get_email_address(username)
    print(real_email)
    print(email)
    if email != real_email[0]:
        return 0, 'email_does_not_match'
    code = await generate_password(4)
    async with pending_codes_lock:
        pending_codes[username] = code

    status = await send_email(f"""
        Hi {username},

        Welcome back to War of Dots!

        Here is your verification code:        
        {code}
        It is only valid for 30 minutes.

        Enjoy the game!

        – TeaAndPython
    """, email)
    if not status:
        return 0, 'email_invalid'

    return 1, None


async def login2(username, code, steam_id=None):
    async with pending_codes_lock:
        if username in pending_codes:
            real_code = pending_codes[username]
        else:
            real_code = None

    if real_code is None:
        return 0, None, 'expired_code'
    if real_code != code:
        return 0, None, 'wrong_code'

    generated_password = await generate_password(12)
    status = await change_password(username, generated_password)
    if not status:
        return 0, None, 'expired_code'

    await update_last_active(username)
    if steam_id is not None:
        await add_steam_id(username, steam_id)

    return 1, generated_password, None



async def steam_login(steam_id):
    print(steam_id)
    username = await get_username(steam_id)
    print(username)
    if username is None:
        return 0, 'user-not-found', None, None
    generated_password = await generate_password(12)
    status = await change_password(username, generated_password)
    print(status)
    if not status:
        return 0, 'user-not-found', None, None

    return 1, None, username, generated_password


async def steam_register(username, steam_id):
    status = 1 - await user_exists(username)
    if not status:
        return 0, 'username_taken', None, None

    status = 1 - await steam_id_exists(steam_id)
    if not status:
        return 0, 'steam-id-taken', None, None
    print(status)
    generated_password = await generate_password(12)
    status = await add_user(username, generated_password, None, steam_id)
    print(status)
    if not status:
        return 0, 'username_taken', None, None

    return 1, None, username, generated_password



async def update_last_active(username: str):
    def blocking_update():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()
        last_active = time.time()
        c.execute('UPDATE users SET last_active = ? WHERE username = ?', (last_active, username))
        conn.commit()
        conn.close()

    await asyncio.to_thread(blocking_update)


# ACCOUNT STATS RELATED

async def set_title(username, title):
    def blocking_get():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()
        c.execute('UPDATE users SET title = ? WHERE username = ?', (title, username))
        conn.commit()
        conn.close()
        return

    return await asyncio.to_thread(blocking_get)


async def buy_item(username, item, price):
    def blocking_get():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()
        c.execute('SELECT money FROM users WHERE username = ?', (username,))
        result = c.fetchone()
        if result[0] is None:
            conn.close()
            return 0, 'error'
        if result[0] < price:
            conn.close()
            return 0, 'error'
        new_money = result[0] - price
        c.execute('UPDATE users SET money = ? WHERE username = ?', (new_money, username))

        c.execute('SELECT items FROM users WHERE username = ?', (username,))
        result = c.fetchone()
        items = json.loads(result[0])
        items.append(item)
        items_json = json.dumps(items)
        c.execute("UPDATE users SET items = ? WHERE username = ?", (items_json, username))

        conn.commit()
        conn.close()
        return 1, None

    if price < 0:
        return 0, 'invalid-price'
    status, error = await asyncio.to_thread(blocking_get)
    return status, error


async def get_stats(username):
    def blocking_get():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()

        # Get the user's score
        c.execute("SELECT score, title, number_of_games, number_of_wins, money, items, stats FROM users WHERE username = ?", (username,))
        result = c.fetchone()
        if not result:
            conn.close()
            return 0, 'get-stats-fail', {}

        score = result[0]
        title = result[1]
        number_of_games = result[2]
        number_of_wins = result[3]
        money = result[4]
        items = json.loads(result[5])
        try:
            other_stats = json.loads(result[6]) if result[6] else {}
        except json.JSONDecodeError:
            other_stats = {}

        # Count users with a higher score (rank = count + 1)
        c.execute("SELECT COUNT(*) FROM users WHERE score > ?", (score,))
        higher_count = c.fetchone()[0]
        conn.close()

        other_stats = DEFAULT_STATS.copy() | other_stats

        return 1, None, {"username": username, "title": title, "score": score, "rank": higher_count + 1,
                         "number_of_games": number_of_games, "number_of_wins": number_of_wins,
                         "units_destroyed": other_stats['units_destroyed'],
                         "shortest_game": other_stats['shortest_game'],
                         "minimal_casualties": other_stats['minimal_casualties'],
                         "dev_defeated": other_stats['dev_defeated'],
                         "campaign_completed": other_stats['campaign_completed'], 'money': money, 'items': items}

    return await asyncio.to_thread(blocking_get)


async def sync_campaign(username, progress):
    def blocking_sync():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()

        # Fetch current stats
        c.execute('SELECT stats FROM users WHERE username = ?', (username,))
        row = c.fetchone()
        if row is None:
            conn.close()
            return 0, 'user-not-found', [], False

        try:
            stats = json.loads(row[0]) if row[0] else {}
        except json.JSONDecodeError:
            stats = {}

        # Merge with defaults to fill missing keys safely
        stats = DEFAULT_STATS.copy() | stats

        # Merge campaign progress (union of existing and new)
        existing_progress = set(stats.get('campaign_progress', []))
        new_progress = set(progress)
        merged_progress = list(existing_progress | new_progress)
        stats['campaign_progress'] = merged_progress

        # Set campaign_completed if indicated
        if len(progress) > 29:
            campaign_completed = True
            stats['campaign_completed'] = True
        else:
            campaign_completed = False

        # Write back to DB
        c.execute('UPDATE users SET stats = ? WHERE username = ?', (json.dumps(stats), username))
        conn.commit()
        conn.close()

        return 1, None, merged_progress, campaign_completed

    return await asyncio.to_thread(blocking_sync)


# GAME RELATED

async def update_elo(score_a, score_b, k=50):
    def expected_score(r1, r2):
        return 1 / (1 + 10 ** ((r2 - r1) / 400))

    expected_a = expected_score(score_a, score_b)

    delta = k * (1 - expected_a)

    return delta


async def score_game(players, winner, additional_info=None, elo=True):
    if winner is None:
        elo = False

    if elo:
        # Get current scores
        scores = await asyncio.gather(*[get_score(player.username) for player in players])
        scores = [score for score in scores]

        deltas = [0 for player in players]

        for i in range(len(players)):
            if i != winner:
                # Update ELO deltas
                delta = await update_elo(scores[winner], scores[i])
                deltas[winner] += delta
                deltas[i] -= delta

        for i in range(len(scores)):
            scores[i] = round(scores[i] + deltas[i])

    # Write updates to DB in a thread
    def blocking_score():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()

        try:
            # Update number of games for players
            for player in players:
                c.execute('UPDATE users SET number_of_games = number_of_games + 1 WHERE username = ?', (player.username,))

            if winner is not None:
                # Update number of wins for winner
                c.execute('UPDATE users SET number_of_wins = number_of_wins + 1 WHERE username = ?', (players[winner].username,))
                c.execute('UPDATE users SET money = money + ? WHERE username = ?', (len(players) - 1, players[winner].username,))

            if elo:
                # Update the scores
                for j in range(len(players)):
                    c.execute('UPDATE users SET score = ? WHERE username = ?', (scores[j], players[j].username))

            if additional_info:
                for j in range(len(players)):
                    c.execute('SELECT stats FROM users WHERE username = ?', (players[j].username,))
                    result = c.fetchone()

                    if result is None:
                        result = {}
                    else:
                        try:
                            result = json.loads(result[0]) if result[0] else {}
                        except json.JSONDecodeError:
                            result = {}

                    result = DEFAULT_STATS.copy() | result

                    destroyed = result['units_destroyed']
                    if len(players) == 2:
                        destroyed += additional_info['casualties'][1 - j]
                    else:
                        total = 0
                        for k in additional_info['casualties']:
                            total += k
                        destroyed += int(total / len(players))

                    result['units_destroyed'] = destroyed

                    if winner == j:
                        if result['shortest_game'] >= additional_info['time']:
                            # No cheating check
                            if additional_info['casualties'][0] > 0 or additional_info['casualties'][1] > 0:
                                result['shortest_game'] = additional_info['time']

                        if result['minimal_casualties'] > additional_info['casualties'][winner]:
                            # No cheating check
                            if additional_info['casualties'][0] > 0 or additional_info['casualties'][1] > 0:
                                result['minimal_casualties'] = additional_info['casualties'][winner]
                        if len(players) == 2:
                            if players[1 - winner].username == 'TeaAndPython':
                                result['dev_defeated'] = True

                    result = json.dumps(result)
                    c.execute('UPDATE users SET stats = ? WHERE username = ?', (result, players[j].username))

            conn.commit()
        finally:
            conn.close()

    await asyncio.to_thread(blocking_score)


async def get_score(username):
    def blocking_get():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()
        c.execute('SELECT score FROM users WHERE username = ?', (username,))
        result = c.fetchone()
        conn.close()
        return result

    score = await asyncio.to_thread(blocking_get)
    return score[0] if score else 0


async def get_titles(usernames):
    titles = []

    def blocking_get():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()

        for username in usernames:
            c.execute('SELECT title FROM users WHERE username = ?', (username,))
            result = c.fetchone()
            if result:
                result = result[0]
                if result is None:
                    result = ''
                else:
                    result = '  ' + result
            titles.append(result)

        conn.close()

        return titles

    return await asyncio.to_thread(blocking_get)


async def notify_spectator(spectator, data):
    status = await send_orjson(spectator.writer, data)
    if not status:
        await disconnect(spectator)


async def disconnect(player):
    print(f"[DISCONNECT] {player.username} disconnected")
    await remove_online_user(player.username)
    try:
        player.writer.close()
        await player.writer.wait_closed()
    except Exception as e:
        print(f"[ERROR] disconnect() for {player.username if player else 'Unknown'}: {e}")


async def is_connected(player):
    try:
        if await send_orjson(player.writer, orjson.dumps("check")) == 0:
            return False

        response = await asyncio.wait_for(read_orjson(player.reader), timeout=1)

        return orjson.loads(response) == "check"

    except Exception as e:
        print(f"[ERROR] is_connected: {e}")
        return False


async def read_orjson(reader):
    try:
        length_bytes = await asyncio.wait_for(reader.readexactly(4), timeout=10)
        length = struct.unpack('>I', length_bytes)[0]
        data = await asyncio.wait_for(reader.readexactly(length), timeout=1)
        return data
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError, Exception) as e:
        return 0


async def receive_ingame(reader):
    try:
        length_bytes = await asyncio.wait_for(reader.readexactly(4), timeout=0.8)
        length = struct.unpack('>I', length_bytes)[0]

        data = await asyncio.wait_for(reader.readexactly(length), timeout=0.5)
        return orjson.loads(data)

    except asyncio.TimeoutError:
        return {}

    except (asyncio.IncompleteReadError, socket.error, ConnectionResetError, BrokenPipeError, Exception) as e:
        return {'end-game': 'connection-lost'}


async def send_orjson(writer, message):
    try:
        length_prefix = struct.pack('>I', len(message))
        writer.write(length_prefix + message)
        await asyncio.wait_for(writer.drain(), timeout=5)
        return 1
    except (asyncio.TimeoutError, socket.error, ConnectionResetError, BrokenPipeError, Exception) as e:
        return 0


async def game_session(mode, players, custom_map=None, score=True, spectators=None):
    active_players = []
    spectators = spectators or []

    try:
        if custom_map:
            map_final = 0
        else:
            if mode == '1v1':
                map_final = random.randint(1, 30)
            elif mode == 'v3':
                map_final = random.randint(31, 33)
            elif mode == 'v4':
                map_final = random.randint(37, 39)
            else:
                map_final = 39

        peace_count = 0
        peace_timer = 0

        random.shuffle(players)
        active_players = [player for player in players]

        titles = await get_titles([player.username for player in players])
        usernames = [[f'{players[i].username}{titles[i]}'] for i in range(len(players))]

        for i in range(len(players)):
            await send_orjson(players[i].writer, orjson.dumps({'color': i, 'map': str(map_final), 'players': usernames}))

        for spectator in spectators:
            asyncio.create_task(send_orjson(spectator.writer, orjson.dumps({'color': None, 'map': str(map_final), 'players': usernames})))

        print(f"[GAME] {mode} started: {[player.username for player in players]}")
        await asyncio.sleep(1)

        while True:
            start_time = time.monotonic()

            data = await asyncio.gather(*[receive_ingame(player.reader) for player in active_players])
            data = [element for element in data]

            # Check for end
            if mode == '1v1':
                message1, message2 = data
                if 'end-game' in message1 or 'end-game' in message2:
                    # Notify spectators
                    for spectator in spectators:
                        asyncio.create_task(send_orjson(spectator.writer, orjson.dumps({'end-game': -1})))

                    # Check win conditions
                    if 'end-game' in message1 and 'end-game' in message2:
                        if message1['end-game'] == message2['end-game'] == 0:
                            await score_game(players, 0, additional_info=message1['stats'], elo=score)
                            print(f'[GAME END] Winner: {players[0].username}')
                            break

                        if message1['end-game'] == message2['end-game'] == 1:
                            await score_game(players, 1, additional_info=message2['stats'], elo=score)
                            print(f'[GAME END] Winner: {players[1].username}')
                            break

                        if message1['end-game'] == 'connection-lost' or message1['end-game'] == 'surrender':
                            await score_game(players, 1, additional_info=message2['stats'] if 'stats' in message2 else None, elo=score)
                            print(f'[GAME END] Winner: {players[1].username}')
                            break

                        if message2['end-game'] == 'connection-lost' or message2['end-game'] == 'surrender':
                            await score_game(players, 0, additional_info=message1['stats'] if 'stats' in message1 else None, elo=score)
                            print(f'[GAME END] Winner: {players[0].username}')
                            break

                        print(f'[GAME END] Winner: None')

                    if 'end-game' in message1:
                        if message1['end-game'] == 0 or message1['end-game'] == 1:
                            await send_orjson(players[1].writer, orjson.dumps({'end-game': 1}))
                            response = await read_orjson(players[1].reader)
                            if not response:
                                await score_game(players, 0, additional_info=message1['stats'], elo=score)
                                print(f'[GAME END] Winner: {players[0].username}')
                                break

                            response = orjson.loads(response)
                            if response['end-game'] == message1['end-game']:
                                if response['end-game'] == 0:
                                    await score_game(players, 0, additional_info=message1['stats'], elo=score)
                                    print(f'[GAME END] Winner: {players[0].username}')

                                else:
                                    await score_game(players, 1, additional_info=message1['stats'], elo=score)
                                    print(f'[GAME END] Winner: {players[1].username}')

                                break

                            print(f'[GAME END] Winner: None')
                            break

                        await send_orjson(players[1].writer, orjson.dumps({'end-game': 1}))
                        await score_game(players, 1, additional_info=message1['stats'], elo=score)
                        print(f'[GAME END] Winner: {players[1].username}')
                        break

                if 'end-game' in message2:
                    if message2['end-game'] == 0 or message2['end-game'] == 1:
                        await send_orjson(players[0].writer, orjson.dumps({'end-game': 1}))
                        response = await read_orjson(players[0].reader)
                        if not response:
                            await score_game(players, 1, additional_info=message2['stats'], elo=score)
                            print(f'[GAME END] Winner: {players[1].username}')
                            break

                        response = orjson.loads(response)
                        if response['end-game'] == message2['end-game']:
                            if response['end-game'] == 0:
                                await score_game(players, 0, additional_info=message2['stats'], elo=score)
                                print(f'[GAME END] Winner: {players[0].username}')

                            else:
                                await score_game(players, 1, additional_info=message2['stats'], elo=score)
                                print(f'[GAME END] Winner: {players[1].username}')

                            break

                        print(f'[GAME END] Winner: None')
                        break

                    await send_orjson(players[0].writer, orjson.dumps({'end-game': 1}))
                    await score_game(players, 0, additional_info=message2['stats'], elo=score)
                    print(f'[GAME END] Winner: {players[0].username}')
                    break

            else:
                end_game = False
                winner = None

                # Count active players
                count = 0
                for i in range(len(data) - 1, -1, -1):
                    if 'end-game' in data[i]:
                        if data[i]['end-game'] == 'connection-lost' or data[i]['end-game'] == 'surrender':
                            await disconnect(active_players[i])
                            active_players.pop(i)
                            data.pop(i)
                    else:
                        count += 1

                # Game ended because not enough players active
                if count < 2:
                    end_game = True
                    if count == 0:
                        winner = None
                    else:
                        winner = players.index(active_players[0])

                    await send_orjson(active_players[0].writer, orjson.dumps({'end-game': 1}))
                    response = await read_orjson(active_players[0].reader)
                    if response:
                        await score_game(players, winner, additional_info=response['stats'], elo=score)
                    else:
                        await score_game(players, winner, elo=score)

                else:
                    # Check if someone has won
                    message = None
                    for i in range(len(data)):
                        if 'end-game' in data[i]:
                            message = data[i]
                            end_game = True

                    if end_game:
                        for player in active_players:
                            await send_orjson(player.writer, orjson.dumps({'end-game': -1}))

                        await score_game(players, message['end-game'], additional_info=message['stats'], elo=score)

                if end_game:
                    # Notify spectators
                    for spectator in spectators:
                        asyncio.create_task(notify_spectator(spectator, orjson.dumps({'end-game': -1})))

                    print(f"[GAME END] v34 Winner:{winner}")
                    break

            # Check for peace
            for message in data:
                if 'peace' in message:
                    peace_count += 1
                    peace_timer = 20

            if peace_count >= len(active_players):
                for player in active_players:
                    await send_orjson(player.writer, orjson.dumps({'end-game': 0.5}))

                response = await read_orjson(active_players[0].reader)

                await score_game(players, None, additional_info=response['stats'], elo=score)

                # Notify spectators
                for spectator in spectators:
                    asyncio.create_task(notify_spectator(spectator, orjson.dumps({'end-game': -1})))
                print(f"[GAME END] {mode} PEACE")
                break

            if peace_timer:
                peace_timer -= 1
                if peace_timer == 0:
                    peace_count = 0

            merged = data[0]
            for i in range(1, len(data)):
                merged |= data[i]

            data = orjson.dumps(merged)
            await asyncio.gather(*[send_orjson(player.writer, data) for player in players])

            for spectator in spectators:
                asyncio.create_task(notify_spectator(spectator, data))

            elapsed = time.monotonic() - start_time
            if elapsed < 1.03:
                await asyncio.sleep(1.03 - elapsed)

    except Exception as e:
        print(f"[ERROR] Game: {e}")
    finally:
        for player in active_players:
            await disconnect(player)
        for spectator in spectators:
            await disconnect(spectator)


async def matchmaking_rooms():
    print(f"Matchmaking in rooms running")
    while True:
        async with room_lock:
            for code in rooms:
                asyncio.create_task(rooms[code].check_room())
        await asyncio.sleep(4)


async def matchmaking_1v1():
    print(f"Matchmaking 1v1 running")
    while True:
        players = []

        while len(players) < 2:
            try:
                player = queue_1v1.get_nowait()
                players.append(player)
            except asyncio.QueueEmpty:
                # Remove disconnected players from the current list
                for i in range(len(players) - 1, -1, -1):
                    if not await is_connected(players[i]):
                        await disconnect(players[i])
                        players.pop(i)
                await asyncio.sleep(20)

        players.sort(key=lambda p: p.score)

        matches = []
        while len(players) >= 2:
            match_players = players[:2]
            matches.append(match_players)
            players = players[2:]

        for match_players in matches:
            asyncio.create_task(game_session('1v1', match_players))


async def matchmaking_v34():
    print(f"Matchmaking v34 running")
    players_v3 = []
    players_v4 = []
    players_v34 = []
    while True:
        while len(players_v3) + len(players_v34) < 3 and len(players_v4) + len(players_v34) < 4:
            try:
                player = queue_v3.get_nowait()
                players_v3.append(player)
            except asyncio.QueueEmpty:
                for i in range(len(players_v3) - 1, -1, -1):
                    if not await is_connected(players_v3[i]):
                        await disconnect(players_v3[i])
                        players_v3.pop(i)

            try:
                player = queue_v4.get_nowait()
                players_v4.append(player)
            except asyncio.QueueEmpty:
                for i in range(len(players_v4) - 1, -1, -1):
                    if not await is_connected(players_v4[i]):
                        await disconnect(players_v4[i])
                        players_v4.pop(i)

            try:
                player = queue_v34.get_nowait()
                players_v34.append(player)
            except asyncio.QueueEmpty:
                for i in range(len(players_v34) - 1, -1, -1):
                    if not await is_connected(players_v34[i]):
                        await disconnect(players_v34[i])
                        players_v34.pop(i)

            await asyncio.sleep(1)

        if len(players_v4) + len(players_v34) >= 4:
            selected_players = []
            while len(selected_players) < 4:
                if players_v4:
                    selected_players.append(players_v4[0])
                    players_v4.pop(0)
                elif players_v34:
                    selected_players.append(players_v34[0])
                    players_v34.pop(0)

            asyncio.create_task(game_session('v4', selected_players))
        else:
            selected_players = []
            while len(selected_players) < 3:
                if players_v3:
                    selected_players.append(players_v3[0])
                    players_v3.pop(0)
                elif players_v34:
                    selected_players.append(players_v34[0])
                    players_v34.pop(0)

            asyncio.create_task(game_session('v3', selected_players))


# USER ONLINE MANAGEMENT
async def add_online_user(username):
    async with online_users_lock:
        online_users.add(username)


async def remove_online_user(username):
    async with online_users_lock:
        online_users.discard(username)


async def is_user_online(username):
    async with online_users_lock:
        return username in online_users


async def authorize(username, password):
    def blocking_login():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()
        c.execute('SELECT password_hash FROM users WHERE username = ?', (username,))
        result = c.fetchone()
        conn.close()

        if result:
            stored_hash = result[0]
            return bcrypt.checkpw(password.encode(), stored_hash)
        return False

    result = await asyncio.to_thread(blocking_login)

    if result:
        await update_last_active(username)

    return 1 if result else 0


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    player = None

    try:
        message = await read_orjson(reader)
        if message == 0:
            return

        message = orjson.loads(message)

        if message['version'] != '0.13.3':
            await send_orjson(writer, orjson.dumps({'status': 0, 'error': 'version-fail'}))
            return

        connection_type = message['type']

        if connection_type == 'register1':
            status, error = await register_user(message['username'], message['email'], steam_id=message['steam_id'])
            await send_orjson(writer, orjson.dumps({'status': status, 'error': error}))
            if status:
                print(f"Successfully registered {message['username']} at {message['email']}")
                await asyncio.sleep(1800)  # 30 minutes
                status = await check_if_active(message['username'])
                if not status:
                    # Done only if no confirmation appeared
                    async with pending_codes_lock:
                        del pending_codes[message['username']]
                    await delete_user(message['username'])
            return

        elif connection_type == 'login1':
            status, error = await login1(message['username'], message['email'])
            await send_orjson(writer, orjson.dumps({'status': status, 'error': error}))
            await asyncio.sleep(1800)  # 30 minutes
            async with pending_codes_lock:
                del pending_codes[message['username']]
            return

        elif connection_type == 'login2':
            status, password, error = await login2(message['username'], message['code'], steam_id=message['steam_id'])
            await send_orjson(writer, orjson.dumps({'status': status, 'password': password, 'error': error}))
            return

        elif connection_type == 'steam_register':
            status, error, username, password = await steam_register(message['username'], message['steam_id'])
            await send_orjson(writer, orjson.dumps({'status': status, 'error': error, 'username': username, 'password': password,}))
            return

        elif connection_type == 'steam_login':
            status, error, username, password = await steam_login(message['steam_id'])
            await send_orjson(writer, orjson.dumps({'status': status, 'error': error, 'username': username, 'password': password, }))
            return

        username = message['username']
        password = message['password']

        status = await authorize(username, password)
        print(f"[LOGIN] {username} - {'SUCCESS' if status else 'FAIL'}")
        if not status:
            await send_orjson(writer, orjson.dumps({'status': 0, 'error': 'authorize-fail'}))
            return

        if connection_type == 'get-stats':
            status, error, response = await get_stats(username)
            response['status'] = status
            if error is not None:
                response['error'] = error
            await send_orjson(writer, orjson.dumps(response))
            return

        if connection_type == 'buy-item':
            item = message['item']
            price = message['price']
            status, error = await buy_item(username, item, price)
            response = {'status': status}
            if error is not None:
                response['error'] = error
            await send_orjson(writer, orjson.dumps(response))
            return

        if connection_type == 'set-title':
            await set_title(username, message['title'])
            return

        if connection_type == 'sync-campaign':
            progress = message['progress']
            status, error, progress, completed = await sync_campaign(username, progress)
            response = {'status': status, 'progress': progress, 'completed': completed}
            if error is not None:
                response['error'] = error
            await send_orjson(writer, orjson.dumps(response))
            return

        if not await is_user_online(username):

            # No Delay Set Up
            sock = writer.get_extra_info('socket')
            if sock:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            player = Player(username=username, reader=reader, writer=writer, score=await get_score(username))
            await add_online_user(username)
            code = message['code']
            if code:
                if await room_exists(code):
                    await send_orjson(player.writer, orjson.dumps({'status': 1}))
                    await rooms[code].add_player(player)
                    print(f"[QUEUE] {username} joined a game room")
                else:
                    custom_map = message['custom_map']
                    if custom_map:
                        await send_orjson(player.writer, orjson.dumps({'status': 1, 'action': 'send-map'}))
                        custom_map = await read_orjson(reader)
                    else:
                        await send_orjson(player.writer, orjson.dumps({'status': 1, 'action': None}))
                        custom_map = None

                    room = GameRoom(code, connection_type, custom_map)
                    await create_game_room(code, room)
                    await rooms[code].add_player(player)
                    print(f"[QUEUE] {username} created a game room")
            elif connection_type == '1v1':
                await queue_1v1.put(player)
                await send_orjson(player.writer, orjson.dumps({'status': 1}))
                print(f"[QUEUE] {username} joined 1v1 queue")
            elif connection_type == 'v3':
                await queue_v3.put(player)
                await send_orjson(player.writer, orjson.dumps({'status': 1}))
                print(f"[QUEUE] {username} joined v3 queue")
            elif connection_type == 'v4':
                await queue_v4.put(player)
                await send_orjson(player.writer, orjson.dumps({'status': 1}))
                print(f"[QUEUE] {username} joined v4 queue")
            elif connection_type == 'v34':
                await queue_v34.put(player)
                await send_orjson(player.writer, orjson.dumps({'status': 1}))
                print(f"[QUEUE] {username} joined v34 queue")
            else:
                await remove_online_user(username)
                await send_orjson(writer, orjson.dumps({'status': 0, 'error': 'connection-fail'}))
                player = None
                print(f"[QUEUE] {username} failed to join queue")
        else:
            await send_orjson(writer, orjson.dumps({'status': 0, 'error': 'user-online-fail'}))
            print(f"[QUEUE] {username} failed to join - already online")


    except Exception as e:
        print(f"[ERROR] handle_client: {e}")
        if player:
            await disconnect(player)

    finally:
        if player is None:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception as e:
                print(f"[ERROR] handle_client: {e}")


async def main():
    global queue_1v1, queue_v3, queue_v4, queue_v34, online_users_lock, room_lock, pending_codes_lock

    queue_1v1 = asyncio.Queue()
    queue_v3 = asyncio.Queue()
    queue_v4 = asyncio.Queue()
    queue_v34 = asyncio.Queue()
    online_users_lock = asyncio.Lock()
    room_lock = asyncio.Lock()
    pending_codes_lock = asyncio.Lock()

    server_ip = "0.0.0.0"
    server_port = 9056

    asyncio.create_task(matchmaking_1v1())
    asyncio.create_task(matchmaking_v34())
    asyncio.create_task(matchmaking_rooms())
    server = await asyncio.start_server(handle_client, server_ip, server_port)
    print(f"Server started at {server_ip}:{server_port}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
