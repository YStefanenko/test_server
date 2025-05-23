import socket
import random
import struct
import pickle
import threading
import sqlite3
import bcrypt
import numpy


def encode(message):
    message = pickle.dumps(message)
    message = struct.pack('>I', len(message)) + message
    return message


def decode(message):
    message = pickle.loads(message)
    return message


def send(player_socket, message):
    try:
        player_socket.sendall(message)
        return 1

    except socket.error or socket.timeout as e:
        print('error occurred when sending a message')
        return 0


def receive(connection):
    try:
        prefix = connection.recv(4)
        if not prefix:
            return 0, 0
        length = struct.unpack('>I', prefix)[0]
        message = connection.recv(length)
        return message, prefix

    except socket.error or socket.timeout as e:
        print('error occurred when receiving a message')
        return 0, 0


def check_login(username, password):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('SELECT password_hash FROM users WHERE username = ?', (username,))
    result = c.fetchone()
    conn.close()

    if result:
        stored_hash = result[0]
        if bcrypt.checkpw(password.encode(), stored_hash):
            return 1
    return 0


def score_game(winner, loser):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('UPDATE users SET score = score + 1 WHERE username = ?', (winner,))
    c.execute('UPDATE users SET score = score - 1 WHERE username = ?', (loser,))
    conn.commit()
    conn.close()
    print('Scores updated')


def game_session_1v1(player1, player2):
    end_message = [pickle.dumps('blue'), pickle.dumps('red')]
    while True:
        message1, prefix1 = receive(player1['socket'])
        message2, prefix2 = receive(player2['socket'])

        if message1 == 0 or message2 == 0:
            if message1 == 0:
                send(player2['socket'], encode('red'))
            else:
                send(player1['socket'], encode('blue'))

            player1['socket'].close()
            player2['socket'].close()

            online_users.discard(player1['username'])
            online_users.discard(player2['username'])

            print('Game Interrupted')
            break

        if message1 in end_message or message2 in end_message:
            if message1 == end_message[0] and message2 == end_message[0]:
                winner = decode(message1)
            elif message1 == end_message[1] and message2 == end_message[1]:
                winner = decode(message1)
            else:
                winner = None

            player1['socket'].close()
            player2['socket'].close()

            online_users.discard(player1['username'])
            online_users.discard(player2['username'])

            if winner == 'blue':
                score_game(player1['username'], player2['username'])
            elif winner == 'red':
                score_game(player2['username'], player1['username'])

            print(f"Game Ended. Winner: {player1['username'] if winner == 'blue' else player2['username'] if winner == 'red' else 'None'}")
            break

        send(player1['socket'], prefix2 + message2)
        send(player2['socket'], prefix1 + message1)


def game_session_2v2(player1, player2, player3, player4):
    end_message = [pickle.dumps('blue'), pickle.dumps('red')]
    while True:
        message1, prefix1 = receive(player1['socket'])
        message2, prefix2 = receive(player2['socket'])
        message3, prefix3 = receive(player3['socket'])
        message4, prefix4 = receive(player4['socket'])

        if message1 == 0 or message2 == 0 or message3 == 0 or message4 == 0:
            player1['socket'].close()
            player2['socket'].close()
            player3['socket'].close()
            player4['socket'].close()

            online_users.discard(player1['username'])
            online_users.discard(player2['username'])
            online_users.discard(player3['username'])
            online_users.discard(player4['username'])

            print('Game Interrupted')
            break

        if message1 in end_message or message2 in end_message or message3 in end_message or message4 in end_message:
            winner = {
                'red': 0,
                'blue': 0,
                'none': 0
            }
            winner['blue' if message1 == end_message[0] else 'red' if message1 == end_message[1] else 'none'] += 1
            winner['blue' if message2 == end_message[0] else 'red' if message2 == end_message[1] else 'none'] += 1
            winner['blue' if message3 == end_message[0] else 'red' if message3 == end_message[1] else 'none'] += 1
            winner['blue' if message4 == end_message[0] else 'red' if message4 == end_message[1] else 'none'] += 1

            player1['socket'].close()
            player2['socket'].close()
            player3['socket'].close()
            player4['socket'].close()

            online_users.discard(player1['username'])
            online_users.discard(player2['username'])
            online_users.discard(player3['username'])
            online_users.discard(player4['username'])


            winner = 'red' if winner['red'] > 2 else 'blue' if winner['blue'] > 2 else 'none'
            print(f"Game Ended. Winner: {player1['username'] if winner == 'blue' else player3['username'] if winner == 'red' else 'None'} & {player2['username'] if winner == 'blue' else player4['username'] if winner == 'red' else 'None'}")
            break

        message = encode([decode(message1), decode(message2), decode(message3), decode(message4)])

        send(player1['socket'], message)
        send(player2['socket'], message)
        send(player3['socket'], message)
        send(player4['socket'], message)


SERVER_IP = "0.0.0.0"
SERVER_PORT = 9056

queue_1v1 = []
queue_2v2 = []
online_users = set()

server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.bind((SERVER_IP, SERVER_PORT))

server_socket.listen()
print(f"Server started at {SERVER_IP}:{SERVER_PORT}")

while True:
    connection, address = server_socket.accept()
    connection.settimeout(1)
    message = receive(connection)[0]
    if message == 0:
        connection_type = None
        connection.close()
    else:
        # Check for different types of connection
        connection_type = decode(message)
        # 1v1 battles
        if connection_type[0:3] == '1v1':
            _, username, password = connection_type.split(':')
            status = check_login(username, password)
            if status and username not in online_users:
                online_users.add(username)
                queue_1v1.append({'socket': connection, 'ip': address, 'username': username})
                print(f"{username} connected for 1v1")
            else:
                send(connection, encode('login-fail'))
                connection.close()
        # 2v2 battles
        elif connection_type[0:3] == '2v2':
            _, username, password = connection_type.split(':')
            status = check_login(username, password)
            if status and username not in online_users:
                online_users.add(username)
                queue_2v2.append({'socket': connection, 'ip': address, 'username': username})
                print(f"{username} connected for 2v2")
            else:
                send(connection, encode('login-fail'))
                connection.close()
        # Security check login
        elif connection_type[0:5] == 'login':
            _, username, password = connection_type.split(':')
            status = check_login(username, password)
            send(connection, encode('login-success' if status else 'login-fail'))
            print(f'{username} security check: {status}')
            connection.close()
        # Anything else
        else:
            connection.close()

    if connection_type[0:3] == '1v1':
        if len(queue_1v1) >= 2:
            players = []
            i = 0
            while len(players) < 2 <= len(queue_1v1):
                send(queue_1v1[i]['socket'], encode('check'))
                message = receive(queue_1v1[i]['socket'])[0]
                if message == 0:
                    print(f"{queue_1v1[i]['username']} disconnected")
                    online_users.discard(queue_1v1[i]['username'])
                    queue_1v1.remove(queue_1v1[i])
                else:
                    players.append(queue_1v1[i])
                    i += 1

            if len(players) == 2:
                queue_1v1.remove(players[0])
                queue_1v1.remove(players[1])

                map_final = random.randint(1, 15)

                send(players[0]['socket'], encode(f"blue:{map_final}"))
                send(players[1]['socket'], encode(f"red:{map_final}"))

                print(f"Matched {players[0]['username']} <--> {players[1]['username']}")
                threading.Thread(target=game_session_1v1, args=(players[0], players[1]), daemon=True).start()

    if connection_type[0:3] == '2v2':
        if len(queue_2v2) >= 4:
            players = []
            i = 0
            while len(players) < 4 <= len(queue_2v2):
                send(queue_2v2[i]['socket'], encode('check'))
                message = receive(queue_2v2[i]['socket'])[0]
                if message == 0:
                    print(f"{queue_2v2[i]['username']} disconnected")
                    online_users.discard(queue_2v2[i]['username'])
                    queue_2v2.remove(queue_2v2[i])
                else:
                    players.append(queue_2v2[i])
                    i += 1

            if len(players) == 4:
                queue_2v2.remove(players[0])
                queue_2v2.remove(players[1])
                queue_2v2.remove(players[2])
                queue_2v2.remove(players[3])

                map_final = random.randint(1, 15)

                send(players[0]['socket'], encode(f"blue:{map_final}"))
                send(players[1]['socket'], encode(f"blue:{map_final}"))
                send(players[2]['socket'], encode(f"red:{map_final}"))
                send(players[3]['socket'], encode(f"red:{map_final}"))

                print(f"Matched {players[0]['username']} & {players[1]['username']} <--> {players[2]['username']} & {players[3]['username']}")
                threading.Thread(target=game_session_2v2, args=(players[0], players[1], players[2], players[3]), daemon=True).start()
