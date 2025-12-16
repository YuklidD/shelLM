from groq import Groq
from dotenv import dotenv_values
import yaml
import os
from datetime import datetime

class LLMTerminal:
    def __init__(self, session_id="default", config_path=".env", personality_path="personalitySSH.yml"):
        self.config = dotenv_values(config_path)
        # Allow overriding model via environment variable for continuous fine-tuning/upgrades
        self.model = os.getenv("SHELLM_MODEL", "llama-3.3-70b-versatile")
        
        # Initialize Groq client
        # Note: In a real K8s env, you might want to handle missing keys more gracefully
        api_key = self.config.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
        try:
            self.client = Groq(api_key=api_key)
        except Exception as e:
            print(f"Failed to init Groq client: {e}", flush=True)
            self.client = None
        
        self.session_id = session_id
        self.history = []
        self.personality_path = personality_path
        
        # Load personality/system prompt
        self.system_prompt = self._load_personality()
        
        # Initialize conversation history
        self.messages = [{"role": "system", "content": self.system_prompt}]
        
        # Log file for this session
        self.log_file = f"session_{self.session_id}.log"

    def _load_personality(self):
        """Loads the system prompt from the YAML file."""
        try:
            with open(self.personality_path, 'r', encoding="utf-8") as file:
                identity = yaml.safe_load(file)
            
            base_prompt = identity['personality']['prompt']
            
            # Dynamic additions (date, etc.) - keeping logic from original script
            today = datetime.now()
            full_prompt = (
                base_prompt + 
                f"\nBased on these examples make something of your own (different username and hostname) to be a starting message. "
                f"Always start the communication in this way and make sure your output ends with '$'. "
                f"For the last login date use {today}\n"
                "Ignore date-time in <> after user input. This is not your concern.\n"
            )
            return full_prompt
        except Exception as e:
            print(f"Error loading personality: {e}")
            return "You are a Linux terminal."

    def log_interaction(self, role, content):
        """Logs interactions to a file."""
        timestamp = datetime.now().isoformat()
        with open(self.log_file, "a+", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {role}: {content}\n")

    def get_response(self, user_input):
        """
        Sends user input to the LLM and returns the response.
        Handles special cases like empty input or specific commands if needed.
        """
        # Add user input to messages
        # We append the timestamp as per original logic to track timing, though the prompt ignores it
        timestamped_input = f"{user_input}\t<{datetime.now()}>\n"
        self.messages.append({"role": "user", "content": timestamped_input})
        self.log_interaction("user", user_input)

        if not self.client:
            return "Error: LLM API Key not configured. Please check server logs."

        try:
            res = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                max_tokens=800
            )
            
            msg = res.choices[0].message.content
            
            # Clean up response (remove backticks as per original)
            msg = msg.replace("`", "")
            
            # Handle $cd or similar artifacts if they appear (from original logic)
            if "$cd" in msg or "$ cd" in msg:
                 parts = msg.split("\n")
                 if len(parts) > 1:
                     msg = parts[1]

            # Add assistant response to history
            self.messages.append({"role": "assistant", "content": msg})
            self.log_interaction("assistant", msg)
            
            return msg

        except Exception as e:
            error_msg = f"Error generating response: {e}"
            print(error_msg)
            return ""
