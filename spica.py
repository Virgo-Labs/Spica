import openai
import os
import datetime
from dotenv import load_dotenv
from solana.rpc.api import Client
from solana.keypair import Keypair
from solana.transaction import Transaction
from solana.system_program import TransferParams, transfer
import re

# Load environment variables
def load_env_vars():
    load_dotenv()
    openai_api_key = os.getenv("OPENAI_API_KEY")
    solana_rpc_url = os.getenv("SOLANA_RPC_URL")
    solana_private_key = os.getenv("SOLANA_PRIVATE_KEY")
    solana_public_key = os.getenv("SOLANA_PUBLIC_KEY")

    if not all([openai_api_key, solana_rpc_url, solana_private_key, solana_public_key]):
        raise ValueError("Missing one or more required environment variables.")

    return openai_api_key, solana_rpc_url, solana_private_key, solana_public_key

# Log conversation
def log_conversation(user_input, model_response):
    log_filename = "conversation_log.txt"
    with open(log_filename, 'a') as log_file:
        log_file.write(f"Timestamp: {datetime.datetime.now()}\n")
        log_file.write(f"You: {user_input}\n")
        log_file.write(f"Chatbot: {model_response}\n")
        log_file.write("-" * 50 + "\n")

# Get conversation history
def get_conversation_history():
    try:
        with open("conversation_log.txt", 'r') as file:
            return file.read()
    except FileNotFoundError:
        return ""

# Construct prompt dynamically
def construct_dynamic_prompt(user_input, conversation_history, max_tokens=1000):
    trimmed_history = ""
    for line in reversed(conversation_history.splitlines()):
        if len(trimmed_history.split()) + len(line.split()) <= max_tokens:
            trimmed_history = line + "\n" + trimmed_history
        else:
            break

    return f"""
You are a helpful assistant in a friendly, conversational setting.
You have the following conversation history:
{trimmed_history}

User: {user_input}
Assistant:
"""

# Validate Solana address
def validate_solana_address(address):
    return len(address) == 44

# Validate transaction amount
def validate_transaction_amount(amount):
    try:
        amount = float(amount)
        return amount > 0
    except ValueError:
        return False

# Handle special commands
def handle_special_commands(user_input):
    if "hello" in user_input.lower() or "hi" in user_input.lower():
        return "Hello! How can I assist you today?"
    elif "help" in user_input.lower():
        return display_help_menu()
    elif "exit" in user_input.lower() or "quit" in user_input.lower():
        graceful_shutdown()
    elif "solana balance" in user_input.lower():
        return get_solana_balance_safe()
    elif "send solana" in user_input.lower():
        amount, recipient = parse_solana_transaction_command(user_input)
        if amount and recipient:
            return send_solana_transaction_safe(amount, recipient)
        return "Invalid command format. Use: send solana <amount> to <recipient>"
    else:
        return None

# Display help menu
def display_help_menu():
    commands = {
        "hello": "Greets the chatbot.",
        "help": "Displays this help menu.",
        "exit": "Ends the chat session.",
        "solana balance": "Checks your Solana wallet balance.",
        "send solana <amount> to <recipient>": "Sends SOL to the specified recipient.",
    }
    help_message = "Here are the available commands:\n"
    for command, description in commands.items():
        help_message += f"- {command}: {description}\n"
    return help_message

# Graceful shutdown
def graceful_shutdown():
    print("Chatbot: Saving conversation and shutting down. Goodbye!")
    exit(0)

# Parse Solana transaction command
def parse_solana_transaction_command(user_input):
    match = re.search(r"send solana (\d+(\.\d+)?) to (\S+)", user_input.lower())
    if match:
        amount = float(match.group(1))
        recipient_address = match.group(3)
        return amount, recipient_address
    return None, None

# Get Solana balance safely
def get_solana_balance_safe():
    try:
        _, solana_rpc_url, _, solana_public_key = load_env_vars()
        solana_client = Client(solana_rpc_url)
        balance = solana_client.get_balance(solana_public_key)
        lamports = balance['result']['value']
        sol_balance = lamports / 10**9
        return f"Your Solana balance is: {sol_balance:.9f} SOL"
    except Exception as e:
        return f"Error fetching Solana balance: {str(e)}"

# Send Solana transaction safely
def send_solana_transaction_safe(amount, recipient_public_key):
    try:
        openai_api_key, solana_rpc_url, solana_private_key, _ = load_env_vars()

        if not validate_solana_address(recipient_public_key):
            return "Invalid recipient address."
        if not validate_transaction_amount(amount):
            return "Invalid transaction amount."

        solana_client = Client(solana_rpc_url)
        sender_keypair = Keypair.from_secret_key(bytes.fromhex(solana_private_key))

        transaction = Transaction().add(
            transfer(
                TransferParams(
                    from_pubkey=sender_keypair.public_key,
                    to_pubkey=recipient_public_key,
                    lamports=int(amount * 10**9)
                )
            )
        )
        response = solana_client.send_transaction(transaction, sender_keypair)
        return f"Transaction successful. Transaction ID: {response['result']}"
    except Exception as e:
        return f"Error sending transaction: {str(e)}"

# Get OpenAI response
def get_response(prompt):
    try:
        openai.api_key, _, _, _ = load_env_vars()
        response = openai.Completion.create(
            engine="text-davinci-003",
            prompt=prompt,
            max_tokens=150,
            temperature=0.7,
            n=1,
            stop=None,
        )
        return response.choices[0].text.strip()
    except Exception as e:
        return f"Error: {str(e)}"

# Chat loop
def chat():
    print("Chatbot: Hello! I'm here to chat with you. Type 'exit' to end the conversation.")
    conversation_history = get_conversation_history()

    while True:
        user_input = input("You: ")

        special_response = handle_special_commands(user_input)
        if special_response:
            print(f"Chatbot: {special_response}")
            if "exit" in user_input.lower() or "quit" in user_input.lower():
                break
            continue

        prompt = construct_dynamic_prompt(user_input, conversation_history)
        response = get_response(prompt)

        print(f"Chatbot: {response}")

        log_conversation(user_input, response)
        conversation_history += f"User: {user_input}\nAssistant: {response}\n"

if __name__ == "__main__":
    chat()
