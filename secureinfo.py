from dotenv import load_dotenv

def load_env_vars():
    load_dotenv()
    openai_api_key = os.getenv("OPENAI_API_KEY")
    solana_rpc_url = os.getenv("SOLANA_RPC_URL")
    solana_private_key = os.getenv("SOLANA_PRIVATE_KEY")
    solana_public_key = os.getenv("SOLANA_PUBLIC_KEY")
    
    if not all([openai_api_key, solana_rpc_url, solana_private_key, solana_public_key]):
        raise ValueError("Missing one or more required environment variables.")
    
    return openai_api_key, solana_rpc_url, solana_private_key, solana_public_key
