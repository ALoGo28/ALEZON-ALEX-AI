import os
import requests
from fastapi import FastAPI, HTTPException, Request
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

# Global dictionary to store live stock updates from Shopify Webhooks
LIVE_INVENTORY = {}

class ChatRequest(BaseModel):
    message: str

@app.post("/webhook/inventory")
async def handle_inventory_webhook(request: Request):
    try:
        data = await request.json()
        product_title = data.get("title")
        variants = data.get("variants", [])
        
        if variants:
            inventory_qty = variants[0].get("inventory_quantity", 0)
            LIVE_INVENTORY[product_title] = inventory_qty
            print(f"WEBHOOK RECEIVED: {product_title} is now at {inventory_qty}")
            
        return {"status": "received"}
    except Exception as e:
        print("WEBHOOK ERROR:", str(e))
        return {"status": "error", "detail": str(e)}

def fetch_shopify_products(search_query: str = ""):
    shop = os.getenv("SHOPIFY_SHOP", "rkvtng-v3.myshopify.com").strip()
    fallback_catalog = "- ALEZON Signature Shoes: $120.00\n- ALEZON Classic Sneaker: $95.00\n- ALEZON Streetwear Hoodie: $65.00"
    
    if not shop:
        return fallback_catalog
        
    shop = shop.replace("https://", "").replace("http://", "").strip("/")
    if not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"
        
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
        for p in products[:50]:
            title = p.get("title", "Unknown")
            product_type = p.get("product_type", "Item")
            variants = p.get("variants", [])
            
            if not variants:
                continue
                
            price = variants[0].get("price", "N/A")
            
            # Check LIVE_INVENTORY. 
            # If a webhook hasn't fired yet, it defaults to available (1). 
            # If a webhook set it to 0, it marks it as OUT OF STOCK.
            inventory_qty = LIVE_INVENTORY.get(title, 1)
            
            if inventory_qty > 0:
                stock_status = f"IN STOCK ({inventory_qty} available)"
            else:
                stock_status = "OUT OF STOCK"
                
            catalog.append(f"- {title} ({product_type}): ${price} | Status: {stock_status}")
            
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
        Pay close attention to stock status. If a product says "OUT OF STOCK", politely inform the customer that it is currently sold out.
        
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