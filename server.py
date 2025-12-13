import socket
import threading
import paramiko
import os
import uuid
from core_logic import LLMTerminal

# Generate a host key if it doesn't exist (for local testing)
HOST_KEY_PATH = 'host.key'
if not os.path.exists(HOST_KEY_PATH):
    key = paramiko.RSAKey.generate(2048)
    key.write_private_key_file(HOST_KEY_PATH)

HOST_KEY = paramiko.RSAKey(filename=HOST_KEY_PATH)

class HoneypotServer(paramiko.ServerInterface):
    def __init__(self):
        self.event = threading.Event()

    def check_channel_request(self, kind, chanid):
        if kind == 'session':
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_auth_password(self, username, password):
        # In a real honeypot, you might want to accept all passwords
        # or specific ones. Here we accept everything to let the attacker in.
        print(f"Auth attempt: {username}:{password}")
        return paramiko.AUTH_SUCCESSFUL

    def get_allowed_auths(self, username):
        return 'password'

def handle_connection(client_sock, addr):
    transport = paramiko.Transport(client_sock)
    transport.add_server_key(HOST_KEY)
    server = HoneypotServer()
    try:
        transport.start_server(server=server)
        chan = transport.accept(20)
        if chan is None:
            return

        # Initialize LLM Session with a unique ID
        session_id = str(uuid.uuid4())
        print(f"Starting session {session_id} for {addr}")
        terminal = LLMTerminal(session_id=session_id)
        
        # Initial banner/welcome (optional, or let LLM handle it if prompted)
        # Standard SSH often doesn't print anything until the shell starts
        
        # Get the initial prompt from the LLM (based on the "starting message" logic)
        # We might need to trigger the LLM to give us the first prompt without user input
        # or just print a standard prompt. 
        # The original script generates a "starting message" in the prompt but doesn't output it 
        # until the loop starts.
        
        # In the original script:
        # 1. System prompt is sent.
        # 2. LLM generates the first output (which includes the prompt).
        # Let's mimic that.
        
        # Trigger first response to get the prompt
        # We send an empty string or a special signal to get the initial state
        # But wait, the original script does:
        # messages = [{"role": "system", "content": initial_prompt}]
        # res = client.chat.completions.create(...)
        # So it gets an initial completion immediately.
        
        initial_response = terminal.get_response("") # Trigger start
        chan.send(initial_response)

        while True:
            # We don't print a prompt here because the LLM response *includes* the prompt
            # (e.g., "user@host:~$ ") at the end.
            
            command = ""
            while not command.endswith("\n") and not command.endswith("\r"):
                transport_byte = chan.recv(1)
                if not transport_byte:
                    return # Connection closed
                
                char = transport_byte.decode("utf-8", errors='ignore')
                
                # Basic echo (optional, real terminals echo)
                chan.send(char)
                
                # Handle backspace (basic)
                if char == '\x7f':
                    command = command[:-1]
                    chan.send('\b \b') # Erase on terminal
                else:
                    command += char
            
            chan.send("\r\n") # Newline after command
            
            clean_command = command.strip()
            if clean_command:
                response = terminal.get_response(clean_command)
                # Ensure proper line endings for SSH terminal
                response = response.replace("\n", "\r\n")
                chan.send(response)
            
            # Check for exit condition (if LLM simulates logout)
            # or if user typed exit
            if clean_command == "exit":
                break

    except Exception as e:
        print(f"Connection error: {e}")
    finally:
        transport.close()

def start_server(port=2222):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', port))
    sock.listen(100)
    print(f"Listening for SSH connections on port {port}...")

    while True:
        client, addr = sock.accept()
        threading.Thread(target=handle_connection, args=(client, addr)).start()

if __name__ == "__main__":
    start_server()
