import socket


def game_loop(blue_socket, red_socket):
    while True:
        try:
            blue_data = blue_socket.recv(2048)
            red_data = red_socket.recv(2048)

            if blue_data and red_data:
                blue_socket.sendall(red_data)
                red_socket.sendall(blue_data)

            else:
                raise BrokenPipeError

        except socket.error as e:
            print('error occured')
            blue_socket.close()
            red_socket.close()

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

            game_loop(blue_socket, red_socket)

            red_socket = None
            blue_socket = None
