import asyncio
import struct
import pickle
import sqlite3
import bcrypt
import random
import time
import socket
from email.message import EmailMessage
import aiosmtplib
import os

online_users = set()
rooms = {}
database_name = 'database.db'
queue_1v1 = None
queue_2v2 = None
online_users_lock = None
room_lock = None

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")


class Player:
    def __init__(self, username, reader, writer):
        self.username = username
        self.reader = reader
        self.writer = writer


# Everything needed to create a game room

class GameRoom:
    def __init__(self, code, mode, custom_map=None):
        self.code = code
        self.mode = mode
        self.players = []

        self.custom_map = custom_map

        if self.custom_map is None:
            self.custom_map = pickle.dumps(None)

    async def add_player(self, player):
        self.players.append(player)
        if not len(self.players) == 1:
            await send_pickle(player.writer, self.custom_map)
        if (len(self.players) > 1 and self.mode == '1v1') or (len(self.players) > 3 and self.mode == '2v2'):
            await asyncio.sleep(5)
            await self.start()

    async def start(self):
        if self.mode == '1v1':
            asyncio.create_task(game_session_1v1(self.players, score=False))
        if self.mode == '2v2':
            asyncio.create_task(game_session_2v2(self.players, score=False))
        await delete_game_room(self.code)

    async def check_room(self):
        for player in self.players:
            if not await is_connected(player):
                await disconnect(player)
                self.players.remove(player)

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


# Everything needed to create a new account

async def generate_password(username):
    characters = 'acdefghjkmnpqrtuvwxyzACDEFGHJKMNPQRTUVWXYZ234679'
    password = ''.join(random.choice(characters) for _ in range(12))
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


async def check_if_active(username):
    def blocking_check():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()
        c.execute('SELECT last_active FROM users WHERE username = ?', (username,))
        result = c.fetchone()
        conn.close()

        if result and result[0] is not None:
            last_active = float(result[0])
            return (time.time() - last_active) < 1795  # 30 minutes in seconds
        return False

    return await asyncio.to_thread(blocking_check)


async def add_user(username, password, email):
    def blocking_add():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
        last_active = time.time()  # Seconds since epoch

        try:
            c.execute('''
                INSERT INTO users (
                    username, password_hash, score, number_of_wins,
                    number_of_games, last_active, email
                ) VALUES (?, ?, 1000, 0, 0, ?, ?)
            ''', (username, password_hash, last_active, email))
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


async def register_user(username, email):
    status = 1 - await user_exists(username)
    if not status:
        return 0, 'username-taken'
    status = 1 - await email_exists(email)
    if not status:
        return 0, 'email-taken'
    generated_password = await generate_password(username)
    status = await add_user(username, generated_password, email)
    if not status:
        return 0, 'username-taken'
    status = await send_email(f"""
        Hi {username},
        
        Thank you for registering an account in War of Dots!
        
        Here are your login details. Once you sign in, you’ll stay logged in — no need to enter them again.
        
        Nickname: {username}
        Password: {generated_password}
        You have 30 minutes to log in, otherwise the account will be deactivated.
        
        I am excited to have you in the battle. Thanks again, and enjoy the game!
        
        – TeaAndPython
    """, email)
    if not status:
        await delete_user(username)
        return 0, 'wrong-email'

    return 1, None


# Everything needed for online user management

async def add_online_user(username):
    async with online_users_lock:
        online_users.add(username)


async def remove_online_user(username):
    async with online_users_lock:
        online_users.discard(username)


async def is_user_online(username):
    async with online_users_lock:
        return username in online_users


async def read_pickle(reader):
    try:
        length_bytes = await asyncio.wait_for(reader.readexactly(4), timeout=5)
        length = struct.unpack('>I', length_bytes)[0]
        data = await asyncio.wait_for(reader.readexactly(length), timeout=5)
        return data
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError, Exception) as e:
        print(f"[ERROR] read_pickle: {e}")
        return 0


async def receive_ingame(reader):
    try:
        length_bytes = await asyncio.wait_for(reader.readexactly(4), timeout=0.8)
        length = struct.unpack('>I', length_bytes)[0]

        data = await asyncio.wait_for(reader.readexactly(length), timeout=0.1)
        return pickle.loads(data)

    except asyncio.TimeoutError:
        return {}

    except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError, Exception) as e:
        print(f"[ERROR] read_pickle: {e}")
        return 0

async def send_pickle(writer, message):
    try:
        length_prefix = struct.pack('>I', len(message))
        writer.write(length_prefix + message)
        await asyncio.wait_for(writer.drain(), timeout=5)
        return 1
    except (asyncio.TimeoutError, ConnectionResetError, BrokenPipeError, Exception) as e:
        print(f"[ERROR] send_pickle: {e}")
        return 0


async def update_last_active(username: str):
    def blocking_update():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()
        last_active = time.time()
        c.execute('UPDATE users SET last_active = ? WHERE username = ?', (last_active, username))
        conn.commit()
        conn.close()

    await asyncio.to_thread(blocking_update)


async def check_login(username, password):
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


async def update_elo(score_a, score_b, result, k=50):
    async def expected_score(r1, r2):
        return 1 / (1 + 10 ** ((r2 - r1) / 400))

    expected_a = await expected_score(score_a, score_b)
    expected_b = await expected_score(score_b, score_a)

    new_rating_a = score_a + k * (result - expected_a)
    new_rating_b = score_b + k * ((1 - result) - expected_b)

    return round(new_rating_a), round(new_rating_b)


async def score_game(winner: str, loser: str):
    # Get current scores
    score_winner = await get_score(winner)
    score_loser = await get_score(loser)

    # Update ELO scores
    score_winner, score_loser = await update_elo(score_winner, score_loser, 1)

    # Write updates to DB in a thread
    def blocking_score():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()

        # Update number of games for both players
        c.execute('UPDATE users SET number_of_games = number_of_games + 1 WHERE username = ?', (winner,))
        c.execute('UPDATE users SET number_of_games = number_of_games + 1 WHERE username = ?', (loser,))

        # Update number of wins for winner
        c.execute('UPDATE users SET number_of_wins = number_of_wins + 1 WHERE username = ?', (winner,))

        # Update the scores
        c.execute('UPDATE users SET score = ? WHERE username = ?', (score_winner, winner))
        c.execute('UPDATE users SET score = ? WHERE username = ?', (score_loser, loser))

        conn.commit()
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
    return str(score[0]) if score else 0


async def disconnect(player):
    print(f"[DISCONNECT] {player.username} disconnected")
    await remove_online_user(player.username)
    try:
        player.writer.close()
        await player.writer.wait_closed()
    except Exception as e:
        print(f"[ERROR] disconnect() for {player.username if player else 'Unknown'}: {e}")


async def game_session_1v1(players, score=True):
    try:
        map_final = random.randint(1, 30)
        colors = ['blue', 'red']
        random.shuffle(colors)
        teams = {'blue': [players[i].username for i in range(len(players)) if colors[i] == 'blue'], 'red': [players[i].username for i in range(len(players)) if colors[i] == 'red']}
        await send_pickle(players[0].writer, pickle.dumps({'color': colors[0], 'map': str(map_final), 'players': {'blue': teams['blue'], 'red': teams['red']}}))
        await send_pickle(players[1].writer, pickle.dumps({'color': colors[1], 'map': str(map_final), 'players': {'blue': teams['blue'], 'red': teams['red']}}))
        print(f"[GAME] 1v1 started: {players[0].username} vs {players[1].username}")
        await asyncio.sleep(1)
        while True:
            start_time = time.monotonic()
            data = await asyncio.gather(receive_ingame(players[0].reader), receive_ingame(players[1].reader))

            message1, message2 = data

            if not (type(message1) is dict and type(message2) is dict):

                if message1 == 0 or message2 == 0:
                    print(f"[ERROR] game_session_1v1 is interrupted")

                if message2 == 0 or message2 == 'surrender':
                    await send_pickle(players[0].writer, pickle.dumps('win'))
                    if score:
                        await score_game(teams['blue'][0], teams['red'][0])
                    print(f"[GAME END] 1v1 winner: {teams['blue'][0]}")
                elif message1 == 0 or message1 == 'surrender':
                    await send_pickle(players[1].writer, pickle.dumps('win'))
                    if score:
                        await score_game(teams['red'][0], teams['blue'][0])
                    print(f"[GAME END] 1v1 winner: {teams['red'][0]}")
                elif message1 == 'blue' and message2 == 'blue':
                    if score:
                        await score_game(teams['blue'][0], teams['red'][0])
                    print(f"[GAME END] 1v1 winner: {teams['blue'][0]}")
                elif message1 == 'red' and message2 == 'red':
                    if score:
                        await score_game(teams['red'][0], teams['blue'][0])
                    print(f"[GAME END] 1v1 winner: {teams['red'][0]}")
                else:
                    print("[GAME END] 1v1 winner: No winner")
                break

            else:
                data = pickle.dumps(message1 | message2)
                await asyncio.gather(send_pickle(players[0].writer, data), send_pickle(players[1].writer, data))

            elapsed = time.monotonic() - start_time
            if elapsed < 1.03:
                await asyncio.sleep(1.03 - elapsed)

    except Exception as e:
        print(f"[ERROR] game_session_1v1: {e}")
    finally:
        await disconnect(players[0])
        await disconnect(players[1])


async def game_session_2v2(players, score=True):
    try:
        map_final = random.randint(1, 30)
        colors = ['blue', 'blue', 'red', 'red']
        random.shuffle(colors)
        teams = {'blue': [players[i].username for i in range(len(players)) if colors[i] == 'blue'], 'red': [players[i].username for i in range(len(players)) if colors[i] == 'red']}
        await send_pickle(players[0].writer, pickle.dumps({'color': colors[0], 'map': str(map_final), 'players': {'blue': teams['blue'], 'red': teams['red']}}))
        await send_pickle(players[1].writer, pickle.dumps({'color': colors[1], 'map': str(map_final), 'players': {'blue': teams['blue'], 'red': teams['red']}}))
        await send_pickle(players[2].writer, pickle.dumps({'color': colors[2], 'map': str(map_final), 'players': {'blue': teams['blue'], 'red': teams['red']}}))
        await send_pickle(players[3].writer, pickle.dumps({'color': colors[3], 'map': str(map_final), 'players': {'blue': teams['blue'], 'red': teams['red']}}))
        print(f"[GAME] 2v2 started: {players[0].username} & {players[1].username} vs {players[2].username} & {players[3].username}")
        await asyncio.sleep(1)
        while True:
            start_time = time.monotonic()
            data = await asyncio.gather(receive_ingame(players[0].reader), receive_ingame(players[1].reader), receive_ingame(players[2].reader), receive_ingame(players[3].reader))

            message1, message2, message3, message4 = data

            if not (type(message1) is dict and type(message2) is dict and type(message3) is dict and type(message4) is dict):
                if message1 == 0 or message2 == 0 or message3 == 0 or message4 == 0:
                    print(f"[ERROR] game_session_2v2 is interrupted")
                else:
                    winner = {
                        'red': 0,
                        'blue': 0,
                    }
                    if message1 == 'blue' or message1 == 'red':
                        winner[message1] += 1
                    if message2 == 'blue' or message2 == 'red':
                        winner[message2] += 1
                    if message3 == 'blue' or message3 == 'red':
                        winner[message3] += 1
                    if message4 == 'blue' or message4 == 'red':
                        winner[message4] += 1

                    winner = 'red' if winner['red'] > 2 else 'blue' if winner['blue'] > 2 else 'none'
                    print(f"[GAME END] 2v2 winner: {players[0].username if winner == 'blue' else players[2].username if winner == 'red' else 'None'} & {players[1].username if winner == 'blue' else players[3].username if winner == 'red' else 'None'}")

                break
            else:
                message = pickle.dumps(message1 | message2 | message3 | message4)

                await send_pickle(players[0].writer, message)
                await send_pickle(players[1].writer, message)
                await send_pickle(players[2].writer, message)
                await send_pickle(players[3].writer, message)

            elapsed = time.monotonic() - start_time
            if elapsed < 1.03:
                await asyncio.sleep(1.03 - elapsed)

    except Exception as e:
        print(f"[ERROR] game_session_2v2: {e}")

    finally:
        await disconnect(players[0])
        await disconnect(players[1])
        await disconnect(players[2])
        await disconnect(players[3])


async def is_connected(player):
    try:
        if await send_pickle(player.writer, pickle.dumps("check")) == 0:
            return False

        response = await asyncio.wait_for(read_pickle(player.reader), timeout=1)

        return pickle.loads(response) == "check"

    except Exception as e:
        print(f"[ERROR] is_connected: {e}")
        return False


async def matchmaking_rooms():
    print(f"Matchmaking in rooms running")
    while True:
        async with room_lock:
            for code in rooms:
                asyncio.create_task(rooms[code].check_room())
        await asyncio.sleep(8)


async def matchmaking_1v1():
    print(f"Matchmaking 1v1 running")
    while True:
        players = []
        while len(players) < 2:
            try:
                player = queue_1v1.get_nowait()
                players.append(player)
            except asyncio.QueueEmpty:
                for i in range(len(players) - 1, -1, -1):
                    if not await is_connected(players[i]):
                        await disconnect(players[i])
                        players.pop(i)
                await asyncio.sleep(2)
        asyncio.create_task(game_session_1v1(players))


async def matchmaking_2v2():
    print(f"Matchmaking 2v2 running")
    while True:
        players = []
        while len(players) < 4:
            try:
                player = queue_2v2.get_nowait()
                players.append(player)
            except asyncio.QueueEmpty:
                for i in range(len(players) - 1, -1, -1):
                    if not await is_connected(players[i]):
                        await disconnect(players[i])
                        players.pop(i)
                await asyncio.sleep(2)
        asyncio.create_task(game_session_2v2(players))


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    player = None

    try:
        message = await read_pickle(reader)
        if message == 0:
            return

        message = pickle.loads(message)

        connection_type = message['type']

        if connection_type == 'register':
            username = message['username']
            email = message['email']
            status, error = await register_user(username, email)
            reply = 'register-success' if status else 'register-fail-' + error
            await send_pickle(writer, pickle.dumps(reply))

            if not error:
                print(f'Successfully registered {username} at {email}')

            await asyncio.sleep(1800)  # 30 minutes

            status = await check_if_active(username)

            if not status:
                await delete_user(username)

            return

        username = message['username']
        password = message['password']

        status = await check_login(username, password)
        print(f"[LOGIN] {username} - {'SUCCESS' if status else 'FAIL'}")

        if connection_type == 'login':
            reply = 'login-success' if status else 'login-fail'
            await send_pickle(writer, pickle.dumps(reply))
            return

        elif connection_type == 'get-score':
            score = await get_score(username)
            if score:
                await send_pickle(writer, pickle.dumps({'username': username, 'score': score}))
            else:
                await send_pickle(writer, pickle.dumps('get-score-fail'))
            return score

        if status and not await is_user_online(username):

            # No Delay Set Up
            sock = writer.get_extra_info('socket')
            if sock:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            player = Player(username=username, reader=reader, writer=writer)
            await add_online_user(username)
            code = message['code']
            if code:
                if await room_exists(code):
                    await rooms[code].add_player(player)
                    print(f"[QUEUE] {username} joined a game room")
                else:
                    custom_map = message['custom_map']
                    if custom_map:
                        await send_pickle(player.writer, pickle.dumps('send_map'))
                        custom_map = await read_pickle(reader)
                    room = GameRoom(code, connection_type, custom_map)
                    await create_game_room(code, room)
                    await rooms[code].add_player(player)
                    print(f"[QUEUE] {username} created a game room")
            elif connection_type == '1v1':
                await queue_1v1.put(player)
                print(f"[QUEUE] {username} joined 1v1 queue")
            elif connection_type == '2v2':
                await queue_2v2.put(player)
                print(f"[QUEUE] {username} joined 2v2 queue")
            else:
                await remove_online_user(username)
                player = None
                print(f"[QUEUE] {username} failed to join queue (invalid state or already online)")
        else:
            await send_pickle(writer, pickle.dumps('login-fail'))

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
    global queue_1v1, queue_2v2, online_users_lock, room_lock

    queue_1v1 = asyncio.Queue()
    queue_2v2 = asyncio.Queue()
    online_users_lock = asyncio.Lock()
    room_lock = asyncio.Lock()

    server_ip = "0.0.0.0"
    server_port = 9056

    asyncio.create_task(matchmaking_1v1())
    asyncio.create_task(matchmaking_2v2())
    asyncio.create_task(matchmaking_rooms())
    server = await asyncio.start_server(handle_client, server_ip, server_port)
    print(f"Server started at {server_ip}:{server_port}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
