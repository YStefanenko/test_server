import socket
import random
import struct
import pickle
import threading
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


def game_session_1v1(player1, player2):
    end_message = [pickle.dumps('blue'), pickle.dumps('red')]
    while True:
        message1, prefix1 = receive(player1)
        message2, prefix2 = receive(player2)

        if message1 == 0 or message2 == 0:
            if message1 == 0:
                send(player2, encode('red'))
            else:
                send(player1, encode('blue'))
            player1.close()
            player2.close()
            print('Game Interrupted')
            break

        if message1 in end_message or message2 in end_message:
            if message1 == end_message[0] and message2 == end_message[0]:
                winner = decode(message1)
            elif message1 == end_message[1] and message2 == end_message[1]:
                winner = decode(message1)
            else:
                winner = None

            player1.close()
            player2.close()
            print(f'Game Ended. Winner: {winner}')
            break

        send(player1, prefix2 + message2)
        send(player2, prefix1 + message1)


def game_session_2v2(player1, player2, player3, player4):
    end_message = [pickle.dumps('blue'), pickle.dumps('red')]
    while True:
        message1, prefix1 = receive(player1)
        message2, prefix2 = receive(player2)
        message3, prefix3 = receive(player3)
        message4, prefix4 = receive(player4)

        if message1 == 0 or message2 == 0 or message3 == 0 or message4 == 0:
            player1.close()
            player2.close()
            player3.close()
            player4.close()
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

            player1.close()
            player2.close()
            player3.close()
            player4.close()

            winner = 'red' if winner['red'] > 2 else 'blue' if winner['blue'] > 2 else 'none'
            print(f'Game Ended. Winner: {winner}')
            break

        message = encode([decode(message1), decode(message2), decode(message3), decode(message4)])

        send(player1, message)
        send(player2, message)
        send(player3, message)
        send(player4, message)


SERVER_IP = "0.0.0.0"
SERVER_PORT = 9056

queue_1v1 = []
queue_2v2 = []


server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.bind((SERVER_IP, SERVER_PORT))

server_socket.listen()
print(f"Server started at {SERVER_IP}:{SERVER_PORT}")

while True:
    connection, address = server_socket.accept()
    connection.settimeout(3)
    message = receive(connection)[0]
    if message == 0:
        connection_type = None
        connection.close()
    else:
        connection_type = decode(message)
        if connection_type == '1v1':
            queue_1v1.append([connection, address])
        elif connection_type == '2v2':
            queue_2v2.append([connection, address])
        print(f"Player connected: {address}")

    if connection_type == '1v1':
        if len(queue_1v1) >= 2:
            players = []
            i = 0
            while len(players) < 2 <= len(queue_1v1):
                send(queue_1v1[i][0], encode('check'))
                message = receive(queue_1v1[i][0])[0]
                if message == 0:
                    print(f'Player {queue_1v1[i][1]} disconnected')
                    queue_1v1.remove(queue_1v1[i])
                else:
                    players.append(queue_1v1[i])
                    i += 1

            if len(players) == 2:
                queue_1v1.remove(players[0])
                queue_1v1.remove(players[1])

                map_final = random.randint(1, 15)

                send(players[0][0], encode(f"blue:{map_final}"))
                send(players[1][0], encode(f"red:{map_final}"))

                print(f"Matched {players[0][1]} <--> {players[1][1]}")
                threading.Thread(target=game_session_1v1, args=(players[0][0], players[1][0]), daemon=True).start()

    if connection_type == '2v2':
        if len(queue_2v2) >= 4:
            players = []
            i = 0
            while len(players) < 4 <= len(queue_2v2):
                send(queue_2v2[i][0], encode('check'))
                message = receive(queue_2v2[i][0])[0]
                if message == 0:
                    print(f'Player {queue_2v2[i][1]} disconnected')
                    queue_2v2.remove(queue_2v2[i])
                else:
                    players.append(queue_2v2[i])
                    i += 1

            if len(players) == 4:
                queue_2v2.remove(players[0])
                queue_2v2.remove(players[1])
                queue_2v2.remove(players[2])
                queue_2v2.remove(players[3])

                map_final = random.randint(1, 9)

                send(players[0][0], encode(f"blue:{map_final}"))
                send(players[1][0], encode(f"blue:{map_final}"))
                send(players[2][0], encode(f"red:{map_final}"))
                send(players[3][0], encode(f"red:{map_final}"))

                print(f"Matched {players[0][1]} & {players[1][1]} <--> {players[2][1]} & {players[3][1]}")
                threading.Thread(target=game_session_2v2, args=(players[0][0], players[1][0], players[2][0], players[3][0]), daemon=True).start()
