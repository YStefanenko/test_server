import socket
import struct
import threading


def game_loop(blue_socket, red_socket):
    print('Game started')
    while True:
        try:
            buff = blue_socket.recv(4)
            if buff:
                blue_length = struct.unpack('!I', buff)[0]
                blue_data = buff + blue_socket.recv(blue_length)
            else:
                blue_data = ''.encode()

            buff = red_socket.recv(4)
            if buff:
                red_length = struct.unpack('!I', buff)[0]
                red_data = buff + red_socket.recv(red_length)
            else:
                red_data = ''.encode()

            if blue_data and red_data:
                blue_socket.sendall(red_data)
                red_socket.sendall(blue_data)

            else:
                print('Someone disconnected')
                raise BrokenPipeError

        except socket.error as e:
            print('Error occured')
            blue_socket.close()
            red_socket.close()

            print(e)
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
                test = red_socket.recv(512).decode()
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

            red_socket = None
            blue_socket = None



