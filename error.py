def get_solana_balance_safe(client, public_key):
    try:
        balance = client.get_balance(public_key)
        lamports = balance['result']['value']
        sol_balance = lamports / 10**9
        return f"Your Solana balance is: {sol_balance:.9f} SOL"
    except Exception as e:
        return f"Error fetching Solana balance: {str(e)}"

def send_solana_transaction_safe(client, sender_keypair, recipient_public_key, amount):
    try:
        if not validate_solana_address(recipient_public_key):
            return "Invalid recipient address."
        if not validate_transaction_amount(amount):
            return "Invalid transaction amount."

        transaction = Transaction().add(
            transfer(
                TransferParams(
                    from_pubkey=sender_keypair.public_key,
                    to_pubkey=recipient_public_key,
                    lamports=int(amount * 10**9)
                )
            )
        )
        response = client.send_transaction(transaction, sender_keypair)
        return f"Transaction successful. Transaction ID: {response['result']}"
    except Exception as e:
        return f"Error sending transaction: {str(e)}"
