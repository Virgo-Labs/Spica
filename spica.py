import os
import asyncio
import json
import logging
import base64
import csv
import aiohttp
import pyotp
import base58  # Added missing import
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
    try:
        with open(CACHE_FILE, "r") as f:
            response_cache = json.load(f)
    except json.JSONDecodeError:
        console.print("[yellow]Cache file is corrupted. Initializing empty cache.[/yellow]")
        response_cache = {}
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
        decoded_key = base58.b58decode(private_key)
        if len(decoded_key) != 64:
            raise ValueError("Invalid private key length.")
        keypair = Keypair.from_secret_key(decoded_key)
        wallets[wallet_name] = keypair
        console.print(f"[green]Wallet '{wallet_name}' connected: {keypair.public_key}[/green]")
    except Exception as e:
        console.print(f"[red]Failed to connect wallet: {e}[/red]")

def switch_wallet(new_wallet: str) -> Optional[str]:
    global current_wallet
    if new_wallet in wallets:
        console.print(f"[green]Switched to wallet '{new_wallet}'[/green]")
        current_wallet = new_wallet
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
    except aiohttp.ClientError as e:
        console.print(f"[red]RPC connection error: {e}[/red]")
        return None
    except RPCException as e:
        console.print(f"[red]Error fetching balance: {e}[/red]")
        return None

async def send_solana_transaction(wallet_name: str, recipient: str, amount: float, token_address: Optional[str] = None, decimals: int = 9):
    if wallet_name not in wallets:
        console.print(f"[red]Wallet '{wallet_name}' not found.[/red]")
        return

    if not validate_solana_address(recipient):
        console.print("[red]Invalid recipient address.[/red]")
        return

    if not validate_transaction_amount(str(amount)):
        console.print("[red]Invalid transaction amount.[/red]")
        return

    confirmation = Prompt.ask(f"Are you sure you want to send {amount} {'SOL' if not token_address else 'tokens'} to {recipient}? (yes/no)")
    if confirmation.lower() != "yes":
        console.print("[yellow]Transaction canceled.[/yellow]")
        return

    code = Prompt.ask("Enter your 2FA code")
    if not verify_2fa(code):
        console.print("[red]Invalid 2FA code. Transaction canceled.[/red]")
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
                        amount=int(amount * 10**decimals),  # Use provided decimals
                        decimals=decimals
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
            name = nft.get("name", "Unknown")
            mint_address = nft.get("mint_address", "Unknown")
            collection_name = nft.get("collection", {}).get("name", "Unknown")
            table.add_row(name, mint_address, collection_name)

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
    save
