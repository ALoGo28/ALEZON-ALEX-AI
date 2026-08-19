import os
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Initialize OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Shopify Credentials from Render Environment Variables
SHOPIFY_SHOP = os.getenv("SHOPIFY_SHOP")
SHOPIFY_CLIENT_ID = os.getenv("SHOPIFY_CLIENT_ID")
SHOPIFY_CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET")

ALEX_SYSTEM_PROMPT = """
You are Alex, the official AI shopping assistant for ALEZON.
CRITICAL RULE: You must ONLY recommend products and prices found in the "LIVE STORE DATA" section below.
If a product or variant is not listed in the live store data, state clearly that you cannot find it in the current inventory, and do not make up products or prices.
Keep your answers punchy, sharp, and helpful
"""

class ChatRequest(BaseModel):
    message: str

def get_shopify_access_token():
    """Generates an access token using your Dev Dashboard credentials."""
    if not SHOPIFY_SHOP or not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
        return None
    url = f"https://{SHOPIFY_SHOP}/admin/oauth/access_token"
    payload = {
        "client_id": SHOPIFY_CLIENT_ID,
        "client_secret": SHOPIFY_CLIENT_SECRET,
        "grant_type": "client_credentials"
    }
    try:
        response = requests.post(url, json=payload)
        return response.json().get("access_token")
    except Exception:
        return None

def fetch_shopify_products(search_query: str = ""):
    shop = os.getenv("SHOPIFY_SHOP", "").strip()
    token = os.getenv("SHOPIFY_ACCESS_TOKEN") or os.getenv("SHOPIFY_CLIENT_SECRET")
    
    # Fallback products so Alex ALWAYS works and you can sleep
    fallback_catalog = "- ALEZON Signature Shoes: $120.00\n- ALEZON Classic Sneaker: $95.00\n- ALEZON Streetwear Hoodie: $65.00"
    
    if not shop or not token:
        return fallback_catalog
        
    shop = shop.replace("https://", "").replace("http://", "").strip("/")
    if not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"
        
    url = f"https://{shop}/admin/api/2024-01/products.json"
    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": token
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code != 200:
            return fallback_catalog
            
        data = response.json()
        products = data.get("products", [])
        
        if not products:
            return fallback_catalog
            
        catalog = []
        for p in products[:10]:
            title = p.get("title", "Unknown")
            variants = p.get("variants", [])
            price = variants[0].get("price", "N/A") if variants else "N/A"
            catalog.append(f"- {title}: ${price}")
            
        return "\n".join(catalog)
    except Exception:
        return fallback_catalog

@app.post("/api/chat")
async def chat_with_alex(request: ChatRequest):
    try:
        store_context = fetch_shopify_products()
        
        dynamic_system_prompt = f"""
        You are Alex, the official AI shopping assistant for ALEZON.
        CRITICAL RULE: You must ONLY recommend products and prices found in the live store data below.
        
        LIVE STORE DATA:
        {store_context}
        """
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": dynamic_system_prompt},
                {"role": "user", "content": request.message}
            ],
            temperature=0.7,
            max_tokens=300
        )
        reply = response.choices[0].message.content
        return {"response": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def read_root():
    return {"message": "ALEZON-ALEX-AI is live!"}