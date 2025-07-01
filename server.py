import asyncio
import struct
import pickle
import sqlite3
import bcrypt
import random
import time

online_users = set()
rooms = {}
database_name = 'database.db'
queue_1v1 = None
queue_2v2 = None
online_users_lock = None
room_lock = None


class Player:
    def __init__(self, username, reader, writer):
        self.username = username
        self.reader = reader
        self.writer = writer


class GameRoom:
    def __init__(self, code, mode, host):
        self.code = code
        self.mode = mode
        self.players = [host]

    async def add_player(self, player):
        self.players.append(player)
        if (len(self.players) > 1 and self.mode == '1v1') or (len(self.players) > 3 and self.mode == '2v2'):
            await self.start()

    async def start(self):
        if self.mode == '1v1':
            asyncio.create_task(game_session_1v1(self.players[0], self.players[1]))
        if self.mode == '2v2':
            asyncio.create_task(game_session_2v2(self.players[0], self.players[1], self.players[2], self.players[3]))
        await delete_game_room(self.code)

    async def check_room(self):
        for player in self.players:
            if not await is_connected(player):
                await disconnect(player)
                self.players.remove(player)

        if not self.players:
            await delete_game_room(self.code)


async def add_game_room(code, room):
    async with room_lock:
        rooms[code] = room


async def delete_game_room(code):
    async with room_lock:
        del rooms[code]


async def room_exists(code):
    async with room_lock:
        return code in rooms


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


async def check_login(username, password):
    loop = asyncio.get_running_loop()

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

    result = await loop.run_in_executor(None, blocking_login)
    return 1 if result else 0


async def score_game(winner, loser):
    loop = asyncio.get_running_loop()

    def blocking_score():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()
        c.execute('UPDATE users SET score = score + 1 WHERE username = ?', (winner,))
        c.execute('UPDATE users SET score = score - 1 WHERE username = ?', (loser,))
        conn.commit()
        conn.close()

    await loop.run_in_executor(None, blocking_score)


async def get_score(username):
    loop = asyncio.get_running_loop()

    def blocking_score():
        conn = sqlite3.connect(database_name)
        c = conn.cursor()
        c.execute('SELECT score FROM users WHERE username = ?', (username,))
        result = c.fetchone()
        conn.close()
        return result

    score = await loop.run_in_executor(None, blocking_score)

    if score is None:
        return 0
    else:
        return str(score[0])


async def disconnect(player):
    print(f"[DISCONNECT] {player.username} disconnected")
    await remove_online_user(player.username)
    try:
        player.writer.close()
        await player.writer.wait_closed()
    except Exception as e:
        print(f"[ERROR] disconnect() for {player.username if player else 'Unknown'}: {e}")


async def game_session_1v1(player1, player2):
    try:
        map_final = random.randint(1, 30)
        await send_pickle(player1.writer, pickle.dumps({'color': 'blue', 'map': str(map_final), 'players': {'blue': [player1.username], 'red': [player2.username]}}))
        await send_pickle(player2.writer, pickle.dumps({'color': 'red', 'map': str(map_final), 'players': {'blue': [player1.username], 'red': [player2.username]}}))
        print(f"[GAME] 1v1 started: {player1.username} vs {player2.username}")

        while True:
            start_time = time.monotonic()
            data = await asyncio.gather(receive_ingame(player1.reader), receive_ingame(player2.reader))

            message1, message2 = data

            if not (type(message1) is dict and type(message2) is dict):

                if message1 == 0 or message2 == 0:
                    print(f"[ERROR] game_session_1v1 is interrupted")

                if message2 == 0 or message2 == 'surrender':
                    await send_pickle(player1.writer, pickle.dumps('win'))
                    await score_game(player1.username, player2.username)
                    print(f"[GAME END] 1v1 winner: {player1.username}")
                elif message1 == 0 or message1 == 'surrender':
                    await send_pickle(player2.writer, pickle.dumps('win'))
                    await score_game(player2.username, player1.username)
                    print(f"[GAME END] 1v1 winner: {player2.username}")
                elif message1 == 'blue' and message2 == 'blue':
                    await score_game(player1.username, player2.username)
                    print(f"[GAME END] 1v1 winner: {player1.username}")
                elif message1 == 'red' and message2 == 'red':
                    await score_game(player2.username, player1.username)
                    print(f"[GAME END] 1v1 winner: {player2.username}")
                else:
                    print("[GAME END] 1v1 winner: No winner")
                break

            else:
                data = pickle.dumps(message1 | message2)
                await send_pickle(player1.writer, data)
                await send_pickle(player2.writer, data)

            elapsed = time.monotonic() - start_time
            if elapsed < 1.03:
                await asyncio.sleep(1.03 - elapsed)

    except Exception as e:
        print(f"[ERROR] game_session_1v1: {e}")
    finally:
        await disconnect(player1)
        await disconnect(player2)


async def game_session_2v2(player1, player2, player3, player4):
    try:
        map_final = random.randint(1, 30)
        await send_pickle(player1.writer, pickle.dumps({'color': 'blue', 'map': str(map_final), 'players': {'blue': [player1.username, player2.username], 'red': [player3.username, player4.username]}}))
        await send_pickle(player2.writer, pickle.dumps({'color': 'blue', 'map': str(map_final), 'players': {'blue': [player1.username, player2.username], 'red': [player3.username, player4.username]}}))
        await send_pickle(player3.writer, pickle.dumps({'color': 'red', 'map': str(map_final), 'players': {'blue': [player1.username, player2.username], 'red': [player3.username, player4.username]}}))
        await send_pickle(player4.writer, pickle.dumps({'color': 'red', 'map': str(map_final), 'players': {'blue': [player1.username, player2.username], 'red': [player3.username, player4.username]}}))
        print(f"[GAME] 2v2 started: {player1.username} & {player2.username} vs {player3.username} & {player4.username}")
        while True:
            start_time = time.monotonic()
            data = await asyncio.gather(receive_ingame(player1.reader), receive_ingame(player2.reader), receive_ingame(player3.reader), receive_ingame(player4.reader))

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
                    print(f"[GAME END] 2v2 winner: {player1.username if winner == 'blue' else player3.username if winner == 'red' else 'None'} & {player2.username if winner == 'blue' else player4.username if winner == 'red' else 'None'}")

                break
            else:
                message = pickle.dumps(message1 | message2 | message3 | message4)

                await send_pickle(player1.writer, message)
                await send_pickle(player2.writer, message)
                await send_pickle(player3.writer, message)
                await send_pickle(player4.writer, message)

            elapsed = time.monotonic() - start_time
            if elapsed < 1.03:
                await asyncio.sleep(1.03 - elapsed)

    except Exception as e:
        print(f"[ERROR] game_session_2v2: {e}")

    finally:
        await disconnect(player1)
        await disconnect(player2)
        await disconnect(player3)
        await disconnect(player4)


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
        await asyncio.sleep(10)


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
                await asyncio.sleep(1)
        asyncio.create_task(game_session_1v1(players[0], players[1]))


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
                await asyncio.sleep(1)
        asyncio.create_task(game_session_2v2(players[0], players[1], players[2], players[3]))


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    player = None

    try:
        message = await read_pickle(reader)
        if message == 0:
            return

        message = pickle.loads(message)

        connection_type = message['type']
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
            await add_online_user(username)
            player = Player(username=username, reader=reader, writer=writer)
            code = message['code']
            if code:
                if await room_exists(code):
                    await rooms[code].add_player(player)
                    print(f"[QUEUE] {username} joined a game room")
                else:
                    room = GameRoom(code, connection_type, player)
                    await add_game_room(code, room)
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
