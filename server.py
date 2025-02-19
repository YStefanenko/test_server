import socket
import struct
import threading


def game_loop(blue_socket, red_socket):
    print('Game started')
    while True:
        try:
            blue_length = struct.unpack('!I', blue_socket.recv(4))[0]
            blue_data = blue_socket.recv(blue_length)
            blue_length = struct.pack('!I', blue_length)
            red_length = struct.unpack('!I', red_socket.recv(4))[0]
            red_data = red_socket.recv(red_length)
            red_length = struct.pack('!I', red_length)

            if blue_data and red_data:
                blue_socket.sendall(red_length + red_data)
                red_socket.sendall(blue_length + blue_data)

            else:
                print('someone disconnected')
                raise BrokenPipeError

        except socket.error or struct.error as e:
            print('error occured')
            blue_socket.close()
            red_socket.close()

            print('Game ended')

            print('Blue player disconnected')
            print('Red player disconnected')

            break




# Run the server
if __name__ == "__main__":
    HOST = '0.0.0.0'
    PORT = 9056

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))

    red_socket = None
    blue_socket = None

    games = []

    print('Server is running')
    server.listen(2)

    while True:
        communication_socket, address = server.accept()

        # Check if contact with the blue player is still maintained
        if red_socket is not None:
            try:
                red_socket.sendall('test'.encode())
                test = red_socket.recv(1024).decode()
                if test == b'':
                    red_socket = None
            except (ConnectionResetError, BrokenPipeError):
                red_socket = None


        if red_socket is None:
            red_socket = communication_socket

            print('Red player connected')
        else:
            blue_socket = communication_socket

            print('Blue player connected')

            red_socket.sendall('red'.encode())
            blue_socket.sendall('blue'.encode())

            new_game = threading.Thread(target=game_loop, args=(blue_socket, red_socket), daemon=True).start()
            print('yes')

            red_socket = None
            blue_socket = None



