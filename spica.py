import os
import asyncio
import json
import logging
import base64
import csv
import aiohttp
import pyotp
from getpass import getpass
from typing import Optional, Dict, List
from dotenv import load_dotenv
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts
from solana.publickey import PublicKey
from solana.keypair import Keypair
from solana.transaction import Transaction
from solana.system_program import TransferParams, transfer
from solana.rpc.core import RPCException
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.instructions import transfer_checked, TransferCheckedParams
from cryptography.fernet import Fernet
import openai
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Load environment variables
load_dotenv()

# Initialize rich console
console = Console()

# Constants
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY") or Fernet.generate_key().decode()
CACHE_FILE = "response_cache.json"

# Initialize encryption
fernet = Fernet(ENCRYPTION_KEY.encode())

# Load or initialize cache
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, "r") as f:
        response_cache = json.load(f)
else:
    response_cache = {}

# Wallet management
wallets: Dict[str, Keypair] = {}
current_wallet: Optional[str] = None

# Solana client
solana_client = AsyncClient(SOLANA_RPC_URL)

# OpenAI setup
openai.api_key = OPENAI_API_KEY

# 2FA setup
totp = pyotp.TOTP(pyotp.random_base32())

# Helper Functions
def encrypt_data(data: str) -> str:
    return fernet.encrypt(data.encode()).decode()

def decrypt_data(encrypted_data: str) -> str:
    return fernet.decrypt(encrypted_data.encode()).decode()

def save_cache():
    with open(CACHE_FILE, "w") as f:
        json.dump(response_cache, f)

def validate_solana_address(address: str) -> bool:
    return len(address) == 44

def validate_transaction_amount(amount: str) -> bool:
    try:
        return float(amount) > 0
    except ValueError:
        return False

def verify_2fa(code: str) -> bool:
    return totp.verify(code)

# Wallet Management
def connect_wallet(wallet_name: str, private_key: Optional[str] = None):
    if not private_key:
        private_key = getpass("Enter your private key (base58 encoded): ")
    try:
        keypair = Keypair.from_secret_key(base58.b58decode(private_key))
        wallets[wallet_name] = keypair
        console.print(f"[green]Wallet '{wallet_name}' connected: {keypair.public_key}[/green]")
    except Exception as e:
        console.print(f"[red]Failed to connect wallet: {e}[/red]")

def switch_wallet(new_wallet: str) -> Optional[str]:
    if new_wallet in wallets:
        console.print(f"[green]Switched to wallet '{new_wallet}'[/green]")
        return new_wallet
    else:
        console.print(f"[red]Wallet '{new_wallet}' not found.[/red]")
        return current_wallet

# Solana Functions
async def get_solana_balance(wallet_name: str) -> Optional[float]:
    if wallet_name not in wallets:
        console.print(f"[red]Wallet '{wallet_name}' not found.[/red]")
        return None
    try:
        balance = await solana_client.get_balance(wallets[wallet_name].public_key, commitment=Confirmed)
        lamports = balance["result"]["value"]
        return lamports / 10**9
    except RPCException as e:
        console.print(f"[red]Error fetching balance: {e}[/red]")
        return None

async def send_solana_transaction(wallet_name: str, recipient: str, amount: float, token_address: Optional[str] = None):
    if wallet_name not in wallets:
        console.print(f"[red]Wallet '{wallet_name}' not found.[/red]")
        return

    if not validate_solana_address(recipient):
        console.print("[red]Invalid recipient address.[/red]")
        return

    if not validate_transaction_amount(str(amount)):
        console.print("[red]Invalid transaction amount.[/red]")
        return

    try:
        sender_keypair = wallets[wallet_name]
        recipient_pubkey = PublicKey(recipient)

        if token_address:
            # SPL Token Transfer
            token_pubkey = PublicKey(token_address)
            transaction = Transaction().add(
                transfer_checked(
                    TransferCheckedParams(
                        program_id=TOKEN_PROGRAM_ID,
                        source=sender_keypair.public_key,
                        mint=token_pubkey,
                        dest=recipient_pubkey,
                        owner=sender_keypair.public_key,
                        amount=int(amount * 10**9),  # Adjust for token decimals
                        decimals=9
                    )
                )
            )
        else:
            # SOL Transfer
            transaction = Transaction().add(
                transfer(
                    TransferParams(
                        from_pubkey=sender_keypair.public_key,
                        to_pubkey=recipient_pubkey,
                        lamports=int(amount * 10**9)
                    )
                )
            )

        transaction.sign(sender_keypair)
        response = await solana_client.send_transaction(transaction, sender_keypair, opts=TxOpts(skip_confirmation=False))
        console.print(f"[green]Transaction successful. Transaction ID: {response['result']}[/green]")
    except RPCException as e:
        console.print(f"[red]Transaction failed: {e}[/red]")

async def get_transaction_history(wallet_name: str, limit: int = 5):
    if wallet_name not in wallets:
        console.print(f"[red]Wallet '{wallet_name}' not found.[/red]")
        return

    try:
        pubkey = wallets[wallet_name].public_key
        response = await solana_client.get_signatures_for_address(pubkey, limit=limit)
        transactions = response["result"]

        table = Table(title=f"Transaction History for {wallet_name}")
        table.add_column("Signature", style="cyan")
        table.add_column("Slot", style="magenta")
        table.add_column("Block Time", style="green")

        for tx in transactions:
            table.add_row(tx["signature"], str(tx["slot"]), str(tx["blockTime"]))

        console.print(table)
    except RPCException as e:
        console.print(f"[red]Error fetching transaction history: {e}[/red]")

async def get_nfts(wallet_name: str):
    if wallet_name not in wallets:
        console.print(f"[red]Wallet '{wallet_name}' not found.[/red]")
        return

    try:
        pubkey = wallets[wallet_name].public_key
        url = f"https://api.simplehash.com/api/v0/nfts/owners?wallet_addresses={pubkey}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                nfts = await response.json()

        table = Table(title=f"NFTs for {wallet_name}")
        table.add_column("Name", style="cyan")
        table.add_column("Mint Address", style="magenta")
        table.add_column("Collection", style="green")

        for nft in nfts:
            table.add_row(nft["name"], nft["mint_address"], nft["collection"]["name"])

        console.print(table)
    except Exception as e:
        console.print(f"[red]Error fetching NFTs: {e}[/red]")

async def get_sol_price():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                price_data = await response.json()
                sol_price = price_data["solana"]["usd"]
                console.print(f"[green]Current SOL price: ${sol_price}[/green]")
    except Exception as e:
        console.print(f"[red]Error fetching SOL price: {e}[/red]")

# OpenAI Functions
def get_cached_response(prompt: str) -> Optional[str]:
    return response_cache.get(prompt)

def cache_response(prompt: str, response: str):
    response_cache[prompt] = response
    save_cache()

async def get_openai_response(prompt: str, context: Optional[List[str]] = None) -> str:
    cached_response = get_cached_response(prompt)
    if cached_response:
        return cached_response

    try:
        messages = [{"role": "user", "content": prompt}]
        if context:
            messages = [{"role": "system", "content": " ".join(context)}] + messages

        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=messages,
            max_tokens=150,
            temperature=0.7,
        )
        generated_text = response.choices[0].message["content"].strip()
        cache_response(prompt, generated_text)
        return generated_text
    except Exception as e:
        return f"Error: {str(e)}"

# Main Chatbot
async def chatbot():
    console.print("[bold blue]Welcome to the Advanced Solana Chatbot![/bold blue]")
    console.print("Type 'help' for a list of commands.")

    chat_context = []
    while True:
        user_input = Prompt.ask("You")
        if user_input.lower() in ["exit", "quit"]:
            console.print("[bold red]Goodbye![/bold red]")
            break

        if user_input.lower() == "help":
            console.print(
                """
[bold]Commands:[/bold]
- connect_wallet <wallet_name>: Connect a Solana wallet.
- switch_wallet <wallet_name>: Switch to another connected wallet.
- balance <wallet_name>: Check wallet balance.
- send <wallet_name> <amount> to <recipient> [token_address]: Send SOL or SPL tokens.
- history <wallet_name>: View transaction history.
- nfts <wallet_name>: View NFTs in the wallet.
- price: Get the current SOL price.
- chat <message>: Chat with the AI.
- exit: Exit the chatbot.
"""
            )
            continue

        if user_input.startswith("connect_wallet"):
            _, wallet_name = user_input.split(maxsplit=1)
            connect_wallet(wallet_name)

        elif user_input.startswith("switch_wallet"):
            _, new_wallet = user_input.split(maxsplit=1)
            current_wallet = switch_wallet(new_wallet)

        elif user_input.startswith("balance"):
            _, wallet_name = user_input.split(maxsplit=1)
            balance = await get_solana_balance(wallet_name)
            if balance is not None:
                console.print(f"[green]Balance: {balance:.9f} SOL[/green]")

        elif user_input.startswith("send"):
            parts = user_input.split()
            if len(parts) < 5:
                console.print("[red]Usage: send <wallet_name> <amount> to <recipient> [token_address][/red]")
                continue
            wallet_name, amount, _, recipient, *token_address = parts
            token_address = token_address[0] if token_address else None
            await send_solana_transaction(wallet_name, recipient, float(amount), token_address)

        elif user_input.startswith("history"):
            _, wallet_name = user_input.split(maxsplit=1)
            await get_transaction_history(wallet_name)

        elif user_input.startswith("nfts"):
            _, wallet_name = user_input.split(maxsplit=1)
            await get_nfts(wallet_name)

        elif user_input.startswith("price"):
            await get_sol_price()

        elif user_input.startswith("chat"):
            _, *message = user_input.split()
            prompt = " ".join(message)
            response = await get_openai_response(prompt, chat_context)
            chat_context.append(f"You: {prompt}")
            chat_context.append(f"Chatbot: {response}")
            console.print(f"[bold cyan]Chatbot:[/bold cyan] {response}")

        else:
            console.print("[red]Invalid command. Type 'help' for assistance.[/red]")

# Run the chatbot
if __name__ == "__main__":
    asyncio.run(chatbot())
