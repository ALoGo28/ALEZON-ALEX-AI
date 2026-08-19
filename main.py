import os
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI

app = FastAPI()

# Initialize OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Shopify Credentials from Render Environment Variables
SHOPIFY_SHOP = os.getenv("SHOPIFY_SHOP")
SHOPIFY_CLIENT_ID = os.getenv("SHOPIFY_CLIENT_ID")
SHOPIFY_CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET")

ALEX_SYSTEM_PROMPT = """
You are Alex, the friendly and helpful AI shopping assistant for ALEZON.
Keep your responses punchy, sharp, and structured for quick reading.
Use the provided live store data to help customers find products.
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
    """Fetches products from your Shopify store inventory."""
    token = get_shopify_access_token()
    if not token:
        return "Shopify integration not configured."
    
    url = f"https://{SHOPIFY_SHOP}/admin/api/2026-01/graphql.json"
    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": token
    }
    query = f"""
    {{
      products(first: 10, query: "{search_query}") {{
        edges {{
          node {{
            title
            description
            onlineStoreUrl
            variants(first: 1) {{
              edges {{
                node {{
                  price
                }}
              }}
            }}
          }}
        }}
      }}
    }}
    """
    try:
        response = requests.post(url, json={"query": query}, headers=headers)
        products = response.json().get("data", {}).get("products", {}).get("edges", [])
        catalog_info = "Here are the available products from ALEZON store:\n"
        for p in products:
            node = p["node"]
            title = node["title"]
            price = node["variants"]["edges"][0]["node"]["price"] if node["variants"]["edges"] else "N/A"
            link = node["onlineStoreUrl"] or "Check store"
            catalog_info += f"- {title} (${price}): Link: {link}\n"
        return catalog_info
    except Exception:
        return "Could not fetch store inventory at the moment."

@app.post("/api/chat")
async def chat_with_alex(request: ChatRequest):
    try:
        store_context = fetch_shopify_products(request.message)
        dynamic_system_prompt = f"""
        {ALEX_SYSTEM_PROMPT}
        
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
        ]
        reply = response.choices[0].message.content
        return {"response": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def read_root():
    return {"message": "ALEZON-ALEX-AI is live!"}