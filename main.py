import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

app = FastAPI()

# Enable CORS so your Shopify frontend can talk to this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this to your Shopify domain URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize OpenAI client (pulls your key securely from environment variables)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

class ChatRequest(BaseModel):
    message: str

# Alex's Core System Prompt (His Identity & Boundaries)
ALEX_SYSTEM_PROMPT = """
You are Alex, the virtual stylist and digital concierge for ALEZON, an independent premium footwear and lifestyle brand.
Your tone is confident, understated, knowledgeable, and streetwear-native—never corporate or robotic.
Your goals:
1. Help customers with sizing and fit for ALEZON heavy fleece hoodies, tees, sweatpants, and footwear.
2. Share the design philosophy, craftsmanship, and vision behind ALEZON drops.
3. Keep responses punchy, sharp, and structured for quick reading.
"""

@app.post("/api/chat")
async def chat_with_alex(request: ChatRequest):
    try:
        response = client.chat.completions.create(
            model="gpt-4o",  # Super fast, extremely low cost
            messages=[
                {"role": "system", "content": ALEX_SYSTEM_PROMPT},
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