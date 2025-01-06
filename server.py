import socket


def game_loop(blue_socket, red_socket):
    while True:
        try:
            data = blue_socket.recv(1024)
            if data:
                red_socket.sendall(data)
            else:
                red_socket.sendall(''.encode())
                red_socket.close()

                print('Blue player disconnected')
                print('Red player disconnected')

                break

        except (ConnectionResetError, BrokenPipeError):
            red_socket.sendall(''.encode())
            red_socket.close()

            print('Blue player disconnected')
            print('Red player disconnected')

            break

        try:
            data = red_socket.recv(1024)
            if data:
                blue_socket.sendall(data)
            else:
                blue_socket.sendall(''.encode())
                blue_socket.close()

                print('Red player disconnected')
                print('Blue player disconnected')

                break

        except (ConnectionResetError, BrokenPipeError):
            blue_socket.sendall(''.encode())
            blue_socket.close()

            print('Red player disconnected')
            print('Blue player disconnected')

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



