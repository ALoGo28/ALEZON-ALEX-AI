import os
import json
import requests
from typing import List, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI


# ============================================================
# APP CONFIGURATION
# ============================================================

app = FastAPI(title="ALEZON-ALEX-AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)


# ============================================================
# INVENTORY / PRODUCT CACHE
# ============================================================

LIVE_INVENTORY = {}
PRODUCT_VARIANT_CACHE = {}


# ============================================================
# REQUEST MODELS
# ============================================================

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]


# ============================================================
# SHOPIFY PRODUCT FETCH
# ============================================================

def get_shopify_shop():
    shop = os.getenv(
        "SHOPIFY_SHOP",
        "rkvtng-v3.myshopify.com"
    ).strip()

    shop = (
        shop
        .replace("https://", "")
        .replace("http://", "")
        .strip("/")
    )

    if not shop:
        shop = "rkvtng-v3.myshopify.com"

    if not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"

    return shop


def fetch_shopify_products():
    """
    Fetch products from Shopify's public products.json endpoint.

    Updates:
    - LIVE_INVENTORY
    - PRODUCT_VARIANT_CACHE

    Returns a formatted catalog for Alex.
    """

    shop = get_shopify_shop()

    fallback_catalog = [
        "- ALEZON Signature Shoes: $120.00",
        "- ALEZON Classic Sneaker: $95.00",
        "- ALEZON Streetwear Hoodie: $65.00"
    ]

    url = f"https://{shop}/products.json"

    try:
        response = requests.get(
            url,
            timeout=5
        )

        if response.status_code != 200:
            print(
                f"SHOPIFY ERROR: HTTP {response.status_code}"
            )
            return "\n".join(fallback_catalog)

        data = response.json()
        products = data.get("products", [])

        if not products:
            print("SHOPIFY: No products returned")
            return "\n".join(fallback_catalog)

        catalog = []

        for product in products[:50]:

            title = product.get(
                "title",
                "Unknown Product"
            )

            variants = product.get(
                "variants",
                []
            )

            if variants:

                first_variant = variants[0]

                price = first_variant.get(
                    "price",
                    "N/A"
                )

                variant_id = str(
                    first_variant.get(
                        "id",
                        ""
                    )
                )

                api_qty = first_variant.get(
                    "inventory_quantity",
                    0
                )

                # Cache Shopify variant ID
                if variant_id:
                    PRODUCT_VARIANT_CACHE[
                        title.lower()
                    ] = variant_id

                # Initialize inventory only if
                # webhook has not already populated it.
                if title not in LIVE_INVENTORY:
                    LIVE_INVENTORY[title] = api_qty

            else:
                price = "N/A"

            current_qty = LIVE_INVENTORY.get(
                title,
                0
            )

            if current_qty > 0:
                status = (
                    f"IN STOCK "
                    f"({current_qty} available)"
                )
            else:
                status = "OUT OF STOCK"

            catalog.append(
                f"- {title}: ${price} | "
                f"Status: {status}"
            )

        return "\n".join(catalog)

    except Exception as e:
        print(
            "SHOPIFY FETCH ERROR:",
            str(e)
        )

        return "\n".join(fallback_catalog)


# ============================================================
# CHECKOUT LINK
# ============================================================

def generate_checkout_link(
    product_title: str
) -> str:

    shop = get_shopify_shop()

    fallback_mapping = {
        "alezon signature shoes": "70881412",
        "alezon classic sneaker": "70881382",
        "alezon streetwear hoodie": "70881550"
    }

    title_lower = (
        product_title
        .lower()
        .strip()
    )

    variant_id = PRODUCT_VARIANT_CACHE.get(
        title_lower
    )

    if not variant_id:
        variant_id = fallback_mapping.get(
            title_lower
        )

    if not variant_id:
        raise ValueError(
            f"No Shopify variant found for "
            f"'{product_title}'"
        )

    return (
        f"https://{shop}/cart/"
        f"{variant_id}:1"
    )


# ============================================================
# OPENAI TOOL DEFINITION
# ============================================================

tools = [
    {
        "type": "function",
        "function": {
            "name": "create_checkout_link",
            "description": (
                "Generate a direct Shopify checkout "
                "link for a specific ALEZON product "
                "when the customer wants to buy it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_title": {
                        "type": "string",
                        "description": (
                            "The exact product title "
                            "the customer wants to buy."
                        )
                    }
                },
                "required": [
                    "product_title"
                ]
            }
        }
    }
]


# ============================================================
# SHOPIFY INVENTORY WEBHOOK
# ============================================================

@app.post("/webhook/inventory")
async def handle_inventory_webhook(
    request: Request
):

    try:

        data = await request.json()

        print(
            "WEBHOOK RECEIVED RAW:",
            data
        )

        product_title = data.get(
            "title"
        )

        variants = data.get(
            "variants",
            []
        )

        if product_title and variants:

            first_variant = variants[0]

            inventory_qty = first_variant.get(
                "inventory_quantity",
                0
            )

            variant_id = str(
                first_variant.get(
                    "id",
                    ""
                )
            )

            LIVE_INVENTORY[
                product_title
            ] = inventory_qty

            if variant_id:

                PRODUCT_VARIANT_CACHE[
                    product_title.lower()
                ] = variant_id

            print(
                f"WEBHOOK UPDATED: "
                f"{product_title} = "
                f"{inventory_qty}"
            )

        return {
            "status": "received"
        }

    except Exception as e:

        print(
            "WEBHOOK ERROR:",
            str(e)
        )

        return {
            "status": "error",
            "detail": str(e)
        }


# ============================================================
# CHAT ENDPOINT
# ============================================================

@app.post("/api/chat")
async def chat_with_alex(
    request: ChatRequest
):

    print(
        "CHAT REQUEST RECEIVED:",
        request.model_dump()
    )

    try:

        # ----------------------------------------------------
        # FETCH LIVE SHOPIFY DATA
        # ----------------------------------------------------

        base_context = fetch_shopify_products()

        live_stock_str = "\n".join(
            [
                f"- {item}: {qty} in stock"
                for item, qty
                in LIVE_INVENTORY.items()
            ]
        )

        if not live_stock_str:
            live_stock_str = (
                "- No live inventory data available"
            )

        store_context = (
            f"{base_context}\n\n"
            f"LIVE INVENTORY STATUS:\n"
            f"{live_stock_str}"
        )

        # ----------------------------------------------------
        # SYSTEM PROMPT
        # ----------------------------------------------------

        dynamic_system_prompt = f"""
You are Alex, the official AI shopping assistant
for ALEZON.

You are friendly, knowledgeable, concise, and helpful.

CRITICAL PRODUCT RULES:

1. ONLY recommend products that appear in the
   LIVE STORE DATA below.

2. Respect the exact inventory quantities shown.

3. Never claim that an out-of-stock product is
   available.

4. If a product has 0 inventory, tell the customer
   that it is currently out of stock.

5. If the customer expresses clear intent to purchase
   a product, such as:
   "yes"
   "sure"
   "buy it"
   "I'll take it"
   "proceed"
   "checkout"
   "get it"

   you MUST call the create_checkout_link tool
   for the specific product.

6. Use the exact product title when calling the tool.

LIVE STORE DATA:

{store_context}
"""

        # ----------------------------------------------------
        # BUILD OPENAI MESSAGE HISTORY
        # ----------------------------------------------------

        messages = [
            {
                "role": "system",
                "content": dynamic_system_prompt
            }
        ]

        for msg in request.messages:

            messages.append(
                {
                    "role": msg.role,
                    "content": msg.content
                }
            )

        print(
            "OPENAI MESSAGE COUNT:",
            len(messages)
        )

        # ----------------------------------------------------
        # FIRST OPENAI REQUEST
        # ----------------------------------------------------

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.7,
            max_tokens=300
        )

        response_message = (
            response.choices[0].message
        )

        checkout_url = None

        # ----------------------------------------------------
        # TOOL CALL
        # ----------------------------------------------------

        if response_message.tool_calls:

            tool_call = (
                response_message.tool_calls[0]
            )

            if (
                tool_call.function.name
                == "create_checkout_link"
            ):

                try:

                    args = json.loads(
                        tool_call.function.arguments
                    )

                    product_title = args.get(
                        "product_title"
                    )

                    if not product_title:
                        raise ValueError(
                            "Missing product_title"
                        )

                    checkout_url = (
                        generate_checkout_link(
                            product_title
                        )
                    )

                    # Convert assistant tool-call
                    # message into a normal dictionary.
                    assistant_tool_message = {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": tool_call.id,
                                "type": "function",
                                "function": {
                                    "name": (
                                        tool_call.function.name
                                    ),
                                    "arguments": (
                                        tool_call.function.arguments
                                    )
                                }
                            }
                        ]
                    }

                    messages.append(
                        assistant_tool_message
                    )

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": (
                                "Checkout link generated "
                                f"successfully: "
                                f"{checkout_url}"
                            )
                        }
                    )

                    # ------------------------------------------------
                    # SECOND OPENAI REQUEST
                    # ------------------------------------------------

                    second_response = (
                        client.chat.completions.create(
                            model="gpt-4o",
                            messages=messages,
                            temperature=0.7,
                            max_tokens=300
                        )
                    )

                    final_text = (
                        second_response
                        .choices[0]
                        .message
                        .content
                    )

                    return {
                        "response": (
                            final_text
                            or "Here is your checkout link."
                        ),
                        "checkout_url": checkout_url
                    }

                except Exception as tool_error:

                    print(
                        "TOOL ERROR:",
                        str(tool_error)
                    )

                    raise HTTPException(
                        status_code=500,
                        detail=str(tool_error)
                    )

        # ----------------------------------------------------
        # NORMAL RESPONSE
        # ----------------------------------------------------

        return {
            "response": (
                response_message.content
                or (
                    "Hey! How can I help you "
                    "with ALEZON today?"
                )
            ),
            "checkout_url": None
        }

    except HTTPException:
        raise

    except Exception as e:

        import traceback

        print(
            "CHAT ERROR EXCEPTION:",
            str(e)
        )

        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/")
def read_root():

    return {
        "message": (
            "ALEZON-ALEX-AI is live with "
            "Dynamic Checkout & Memory!"
        )
    }


@app.get("/health")
def health_check():

    return {
        "status": "healthy"
    }