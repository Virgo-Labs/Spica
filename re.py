import re

def parse_solana_transaction_command(user_input):
    match = re.search(r"send solana (\d+(\.\d+)?) to (\S+)", user_input.lower())
    if match:
        amount = float(match.group(1))
        recipient_address = match.group(3)
        return amount, recipient_address
    return None, None
