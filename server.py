import socket

SERVER_IP = "0.0.0.0"  # Listen on all interfaces
SERVER_PORT = 9056

players = []  # Store connected players

# Create UDP socket
server_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
server_sock.bind((SERVER_IP, SERVER_PORT))

print(f"Matchmaking server started on {SERVER_IP}:{SERVER_PORT}")

while True:
    data, address = server_sock.recvfrom(1024)
    print(f"Player connected: {address}")

    players.append(address)

    if len(players) >= 2:
        # Match players
        player1 = players.pop(0)
        player2 = players.pop(0)
        try:
            # Send each player the other's IP and port
            server_sock.sendto(f"blue:{player2[0]}:{player2[1]}".encode(), player1)
            server_sock.sendto(f"red:{player1[0]}:{player1[1]}".encode(), player2)
    
            print(f"Matched {player1} <--> {player2}")
            
        except socket.error:
            pass
