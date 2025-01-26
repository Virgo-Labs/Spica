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
