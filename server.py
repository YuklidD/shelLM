import socket
import threading
import paramiko
import os
import uuid
from datetime import datetime
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
        print(f"Auth attempt: {username}:{password}", flush=True)
        return paramiko.AUTH_SUCCESSFUL

    def get_allowed_auths(self, username):
        return 'password'

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        return True

    def check_channel_shell_request(self, channel):
        self.event.set()
        return True

class ShellEmulator:
    def __init__(self, channel):
        self.channel = channel
        self.buffer = []
        self.cursor_pos = 0
        self.history = []
        self.suggestion = ""
        self.common_commands = ["sudo", "nano", "vim", "cat", "ls", "cd", "pwd", "ping", "ssh", "grep", "history", "clear", "exit"]

    def send(self, data):
        self.channel.send(data)

    def _get_suggestion(self):
        if not self.buffer:
            return ""
        current_cmd = "".join(self.buffer)
        # Check history (most recent first)
        for cmd in reversed(self.history):
            if cmd.startswith(current_cmd) and cmd != current_cmd:
                return cmd
        return ""

    def _render_line(self):
        # Clear from cursor to end of screen (to clean up old ghost text)
        # But we are at cursor_pos.
        # We need to print: [Rest of Buffer] + [Ghost Text] + [Clear Rest] + [Move Back]
        
        rest_of_buffer = "".join(self.buffer[self.cursor_pos:])
        full_buffer = "".join(self.buffer)
        
        ghost_part = ""
        if self.suggestion.startswith(full_buffer) and len(self.suggestion) > len(full_buffer):
            ghost_part = self.suggestion[len(full_buffer):]

        # Construct output
        output = rest_of_buffer.encode()
        
        if ghost_part:
            # Grey color for ghost text
            output += b'\x1b[90m' + ghost_part.encode() + b'\x1b[0m'
        
        output += b'\x1b[K' # Clear to end of line
        
        # Move cursor back to real position
        # We moved forward by len(rest_of_buffer) + len(ghost_part) (if printed)
        # Wait, we printed rest_of_buffer (cursor moves). Then ghost (cursor moves).
        back_steps = len(rest_of_buffer) + len(ghost_part)
        
        if back_steps > 0:
            output += b'\x1b[D' * back_steps
            
        self.send(output)

    def handle_input(self):
        while True:
            char = self.channel.recv(1)
            if not char:
                return None

            # Handle Escape Sequences (Arrows)
            if char == b'\x1b':
                seq = self.channel.recv(2)
                if seq == b'[D': # Left Arrow
                    if self.cursor_pos > 0:
                        self.cursor_pos -= 1
                        self.send(b'\x1b[D')
                elif seq == b'[C': # Right Arrow
                    # If at end of line and have suggestion, accept it
                    if self.cursor_pos == len(self.buffer) and self.suggestion:
                        # Accept suggestion
                        to_add = self.suggestion[len(self.buffer):]
                        for c in to_add:
                            self.buffer.append(c)
                            self.cursor_pos += 1
                            self.send(c.encode())
                        self.suggestion = ""
                        self._render_line()
                    elif self.cursor_pos < len(self.buffer):
                        self.cursor_pos += 1
                        self.send(b'\x1b[C')
                # Ignore Up/Down for now
                continue

            # Handle Tab (Completion)
            if char == b'\t':
                current_word = "".join(self.buffer).split(" ")[-1]
                if current_word:
                    matches = [cmd for cmd in self.common_commands if cmd.startswith(current_word)]
                    if len(matches) == 1:
                        # Complete it
                        completion = matches[0][len(current_word):]
                        for c in completion:
                            self.buffer.insert(self.cursor_pos, c)
                            self.cursor_pos += 1
                            self.send(c.encode())
                        self.send(b' ') # Add space
                        self.buffer.insert(self.cursor_pos, ' ')
                        self.cursor_pos += 1
                        self._render_line()
                continue

            # Handle Backspace
            if char == b'\x7f' or char == b'\x08':
                if self.cursor_pos > 0:
                    # Remove char from buffer
                    self.buffer.pop(self.cursor_pos - 1)
                    self.cursor_pos -= 1
                    # Move back
                    self.send(b'\b')
                    
                    # Update suggestion
                    self.suggestion = self._get_suggestion()
                    
                    # Render
                    self._render_line()
                continue

            # Handle Enter
            if char == b'\r' or char == b'\n':
                self.send(b'\r\n')
                command = "".join(self.buffer)
                if command.strip():
                    self.history.append(command)
                self.buffer = []
                self.cursor_pos = 0
                self.suggestion = ""
                return command

            # Handle Normal Characters
            decoded_char = char.decode("utf-8", errors='ignore')
            if decoded_char.isprintable():
                self.buffer.insert(self.cursor_pos, decoded_char)
                self.cursor_pos += 1
                self.send(char)
                
                # Update suggestion
                self.suggestion = self._get_suggestion()
                
                # Render rest of line + ghost
                self._render_line()

def handle_connection(client_sock, addr):
    transport = paramiko.Transport(client_sock)
    transport.add_server_key(HOST_KEY)
    server = HoneypotServer()
    try:
        transport.start_server(server=server)
        chan = transport.accept(20)
        if chan is None:
            return

        # Wait for shell request
        server.event.wait(10)
        if not server.event.is_set():
            print("Client did not request shell")
            return

        # Initialize LLM Session with a unique ID
        session_id = str(uuid.uuid4())
        print(f"Starting session {session_id} for {addr}")
        terminal = LLMTerminal(session_id=session_id)
        
        # Realistic Banner (Ubuntu/AWS style)
        banner = (
            "Welcome to Ubuntu 22.04.3 LTS (GNU/Linux 6.2.0-1018-aws x86_64)\r\n\r\n"
            " * Documentation:  https://help.ubuntu.com\r\n"
            " * Management:     https://landscape.canonical.com\r\n"
            " * Support:        https://ubuntu.com/advantage\r\n\r\n"
            "  System information as of " + str(datetime.now().strftime("%a %b %d %H:%M:%S UTC %Y")) + "\r\n\r\n"
            "  System load:  0.01               Processes:             98\r\n"
            "  Usage of /:   18.2% of 7.57GB    Users logged in:       0\r\n"
            "  Memory usage: 21%                IPv4 address for eth0: 10.0.0.4\r\n"
            "  Swap usage:   0%\r\n\r\n"
            " * Strictly confined Kubernetes makes edge and IoT secure. Learn how MicroK8s\r\n"
            "   just got even better: https://microk8s.io/\r\n\r\n"
            "0 updates can be applied immediately.\r\n\r\n"
        )
        chan.send(banner)
        
        # Trigger first response to get the prompt
        initial_response = terminal.get_response("") 
        # Fix line endings for raw SSH terminal (needs \r\n)
        initial_response = initial_response.replace("\n", "\r\n")
        chan.send(initial_response)

        shell = ShellEmulator(chan)

        while True:
            command = shell.handle_input()
            if command is None:
                break # Connection closed
            
            clean_command = command.strip()
            if clean_command:
                response = terminal.get_response(clean_command)
                # Ensure proper line endings for SSH terminal
                response = response.replace("\n", "\r\n")
                
                # Fix: Remove trailing newline if present so cursor stays on prompt line
                if response.endswith("\r\n"):
                    response = response[:-2]
                elif response.endswith("\n"):
                    response = response[:-1]
                
                # Fix: Ensure space after prompt '$'
                if response.endswith("$") or response.endswith("$"): # Check for $
                     response += " "
                
                chan.send(response)
            
            # Check for exit condition (if LLM simulates logout)
            # or if user typed exit
            if clean_command == "exit":
                break

    except Exception as e:
        print(f"Connection error: {e}", flush=True)
        import traceback
        traceback.print_exc()
    finally:
        transport.close()

def start_server(port=None):
    if port is None:
        port = int(os.getenv("SSH_PORT", 2222))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', port))
    sock.listen(100)
    print(f"Listening for SSH connections on port {port}...", flush=True)

    while True:
        client, addr = sock.accept()
        print(f"Accepted connection from {addr}", flush=True)
        threading.Thread(target=handle_connection, args=(client, addr)).start()

if __name__ == "__main__":
    start_server()
