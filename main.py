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

ALEX_SYSTEM_PROMPT = """
You are Alex, the official AI shopping assistant for ALEZON.
CRITICAL RULE: You must ONLY recommend products and prices found in the "LIVE STORE DATA" section below.
If a product or variant is not listed in the live store data, state clearly that you cannot find it in the current inventory, and do not make up products or prices.
Keep your answers punchy, sharp, and helpful
"""

class ChatRequest(BaseModel):
    message: str

def fetch_shopify_products(search_query: str = ""):
    # Get your shop from environment variables, defaulting to your store domain
    shop = os.getenv("SHOPIFY_SHOP", "rkvtng-v3.myshopify.com").strip()
    
    # Fallback products just in case the request fails
    fallback_catalog = "- ALEZON Signature Shoes: $120.00\n- ALEZON Classic Sneaker: $95.00\n- ALEZON Streetwear Hoodie: $65.00"
    
    if not shop:
        return fallback_catalog
        
    shop = shop.replace("https://", "").replace("http://", "").strip("/")
    if not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"
        
    # Shopify's public products JSON endpoint needs NO tokens or secrets!
    url = f"https://{shop}/products.json"
    
    try:
        response = requests.get(url, timeout=5)
        print("PUBLIC SHOPIFY STATUS:", response.status_code)
        
        if response.status_code != 200:
            print("PUBLIC SHOPIFY ERROR:", response.text)
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
    except Exception as e:
        print("DIRECT FETCH EXCEPTION:", str(e))
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