import socket

SERVER_IP = '127.0.0.1'
SERVER_PORT = 5000


def main():
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.connect((SERVER_IP, SERVER_PORT))
    f = client_socket.makefile('rw', encoding='utf-8', newline='\n')
    print(f"Connected to server {SERVER_IP}:{SERVER_PORT}\n")

    try:
        while True:
            line = f.readline()
            if not line:                       
                break
            kind, _, text = line.rstrip('\n').partition('|')

            if kind == 'MSG':                  
                print(text)
            elif kind == 'ASK':                
                answer = input(text)
                f.write(answer + '\n')
                f.flush()
            elif kind == 'BYE':                
                print(text)
                break
    finally:
        f.close()
        client_socket.close()
        print("Client disconnected.")


if __name__ == '__main__':
    main()