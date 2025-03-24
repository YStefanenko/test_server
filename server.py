import socket
import random
import threading


def game_session(player1, player2):
    try:
        while True:
            player2.sendall(player1.recv(8192))
            player1.sendall(player2.recv(8192))
    except socket.error as e:
        player1.close()
        player2.close()
        print('game ended')



SERVER_IP = "0.0.0.0"  # Listen on all interfaces
SERVER_PORT = 9056

players = []  # Store connected players

# Create UDP socket
server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.bind((SERVER_IP, SERVER_PORT))

server_socket.listen()
print(f"Server started at {SERVER_IP}:{SERVER_PORT}")

while True:
    player_socket, address = server_socket.accept()
    print(f"Player connected: {address}")

    players.append([player_socket, address])

    if len(players) >= 2:
        # Check connections
        maps =[]
        for player in players:
            try:
                player[0].sendall('check'.encode())
                map_choice = player[0].recv(1024).decode()
                maps.append(map_choice)
            except socket.error as e:
                print(f'Player {player[1]} disconnected')
                players.remove(player)

        if len(players) >= 2:
            try:
                blue_player = players.pop(0)
                red_player = players.pop(0)

                map_final = maps[0]

                blue_player[0].sendall(f"blue:{map_final}".encode())
                red_player[0].sendall(f"red:{map_final}".encode())

                print(f"Matched {blue_player[1]} <--> {red_player[1]}")
                threading.Thread(target=game_session, args=(blue_player[0], red_player[0]), daemon=True).start()

            except socket.error as e:
                print('game ended')
