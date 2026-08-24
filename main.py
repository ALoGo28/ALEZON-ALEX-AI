import os
import json
import requests
from typing import List, Optional
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

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# In-memory storage for live inventory quantities and variant IDs fetched from Shopify
LIVE_INVENTORY = {}
PRODUCT_VARIANT_CACHE = {}

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]

def fetch_shopify_products():
    """Fetches products from Shopify, updates inventory cache, and builds store context."""
    shop = os.getenv("SHOPIFY_SHOP", "rkvtng-v3.myshopify.com").strip()
    fallback_catalog = [
        "- ALEZON Signature Shoes: $120.00\n"
        "- ALEZON Classic Sneaker: $95.00\n"
        "- ALEZON Streetwear Hoodie: $65.00"
    ]
    
    if not shop:
        return "\n".join(fallback_catalog)

    shop = shop.replace("https://", "").replace("http://", "").strip("/")
    if not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"

    url = f"https://{shop}/products.json"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code != 200:
            return "\n".join(fallback_catalog)
            
        data = response.json()
        products = data.get("products", [])
        if not products:
            return "\n".join(fallback_catalog)

        catalog = []
        for p in products[:50]:
            title = p.get("title", "Unknown")
            variants = p.get("variants", [])
            
            if variants:
                first_variant = variants[0]
                price = first_variant.get("price", "N/A")
                variant_id = str(first_variant.get("id", ""))
                api_qty = first_variant.get("inventory_quantity", 1)
                
                PRODUCT_VARIANT_CACHE[title.lower()] = variant_id
                
                # Only initialize if not already tracked by webhook
                if title not in LIVE_INVENTORY:
                    LIVE_INVENTORY[title] = api_qty
            else:
                price = "N/A"

            # Always pull the latest stock count from LIVE_INVENTORY as the source of truth
            current_qty = LIVE_INVENTORY.get(title, 1)
            status = f"IN STOCK ({current_qty} available)" if current_qty > 0 else "OUT OF STOCK"
            catalog.append(f"- {title}: ${price} | Status: {status}")

        return "\n".join(catalog)
    except Exception:
        return "\n".join(fallback_catalog)

def generate_checkout_link(product_title: str) -> str:
    """Dynamically generates a secure Shopify checkout link using cached variant IDs."""
    shop = os.getenv("SHOPIFY_SHOP", "rkvtng-v3.myshopify.com").strip()
    shop = shop.replace("https://", "").replace("http://", "").strip("/")
    if not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"

    # Fallback default variant IDs if cache is empty
    fallback_mapping = {
        "alezon signature shoes": "70881412",
        "alezon classic sneaker": "70881382",
        "alezon streetwear hoodie": "70881550"
    }

    title_lower = product_title.lower().strip()
    variant_id = PRODUCT_VARIANT_CACHE.get(title_lower)

    if not variant_id:
        variant_id = fallback_mapping.get(title_lower, "70881412")

    return f"https://{shop}/cart/{variant_id}:1"

tools = [
    {
        "type": "function",
        "function": {
            "name": "create_checkout_link",
            "description": "Generate a direct secure checkout link for a specific ALEZON product when the user wants to buy it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_title": {
                        "type": "string",
                        "description": "The exact title of the product the user wants to buy."
                    }
                },
                "required": ["product_title"]
            }
        }
    }
]

@app.post("/webhook/inventory")
async def handle_inventory_webhook(request: Request):
    """Webhook to receive real-time product/inventory updates from Shopify."""
    try:
        data = await request.json()
        print("WEBHOOK RECEIVED RAW:", data)

        # Extract product title and variants from Shopify's product payload
        product_title = data.get("title")
        variants = data.get("variants", [])

        if product_title and variants:
            # Get the inventory quantity of the first variant
            inventory_qty = variants[0].get("inventory_quantity", 0)
            variant_id = str(variants[0].get("id", ""))

            # Update your live inventory dictionary using the actual product title
            LIVE_INVENTORY[product_title] = inventory_qty
            
            if variant_id:
                PRODUCT_VARIANT_CACHE[product_title.lower()] = variant_id

            print(f"WEBHOOK UPDATED: {product_title} is now at {inventory_qty}")

        return {"status": "received"}
    except Exception as e:
        print("WEBHOOK ERROR:", str(e))
        return {"status": "error", "detail": str(e)}

@app.post("/api/chat")
async def chat_with_alex(request: ChatRequest):
    try:
        # Fetch base store products
        base_context = fetch_shopify_products()

        # Build a live inventory string dynamically from your webhook dictionary
        live_stock_str = "\n".join([f"- {item}: {qty} in stock" for item, qty in LIVE_INVENTORY.items()])
        
        # Combine them so Alex sees both the products and the real-time live stock counts
        store_context = f"{base_context}\n\nLIVE INVENTORY STATUS:\n{live_stock_str if LIVE_INVENTORY else '- ALEZON Black Hoodie: 1 in stock'}"

        dynamic_system_prompt = f"""
You are Alex, the official AI shopping assistant for ALEZON.
CRITICAL RULE: You must ONLY recommend products found in the live store data below, and you must respect the exact numbers shown in the LIVE INVENTORY STATUS.
If a user expresses intent to buy a product (e.g. 'yes', 'sure', 'proceed', 'buy it'), you MUST immediately call the 'create_checkout_link' tool for that specific product.

LIVE STORE DATA:
{store_context}
        """

        # Build message payload including full multi-turn conversation history
        messages = [{"role": "system", "content": dynamic_system_prompt}]
        for msg in request.messages:
            messages.append({"role": msg.role, "content": msg.content})

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.7,
            max_tokens=300
        )

        response_message = response.choices[0].message
        checkout_url = None

        # Handle OpenAI Function/Tool Calling
        if response_message.tool_calls:
            tool_call = response_message.tool_calls[0]
            if tool_call.function.name == "create_checkout_link":
                args = json.loads(tool_call.function.arguments)
                product_title = args.get("product_title")

                checkout_url = generate_checkout_link(product_title)

                messages.append(response_message)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": "create_checkout_link",
                    "content": f"Checkout link generated successfully: {checkout_url}"
                })

                second_response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=messages
                )
                
                return {
                    "response": second_response.choices[0].message.content,
                    "checkout_url": checkout_url
                }

        return {
            "response": response_message.content,
            "checkout_url": None
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def read_root():
    return {"message": "ALEZON-ALEX-AI is live with Dynamic Checkout & Memory!"}