import os
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from dotenv import load_dotenv
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    PushMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent
)

from config import LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET
from rag.generator import get_rag_response

load_dotenv()

app = FastAPI()

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
parser = WebhookParser(channel_secret=LINE_CHANNEL_SECRET)

# process RAG and push the response in the background
async def process_rag_and_push(user_id: str, user_message: str):
    # call gemini API
    bot_response = get_rag_response(user_message)
    
    # send the response back to the user via LINE Messaging API
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        try:
            line_bot_api.push_message(
                PushMessageRequest(
                    to=user_id,
                    messages=[TextMessage(text=bot_response)]
                )
            )
        except Exception as e:
            print(f"push message error: {e}")

# health check for Render (and an easy way to wake the free instance)
@app.get("/")
async def health():
    return {"status": "ok"}

@app.post("/callback")
async def callback(request: Request, background_tasks: BackgroundTasks):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    body_str = body.decode("utf-8")

    try:
        events = parser.parse(body_str, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature.")

    for event in events:
        if isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
            user_message = event.message.text
            user_id = event.source.user_id

            
            # ignore Gemini API call in the main thread, run it in the background
            background_tasks.add_task(process_rag_and_push, user_id, user_message)
                
    return "OK"

if __name__ == "__main__":
    import uvicorn
    # local development only; on Render the start command in render.yaml is used
    uvicorn.run("main:app", host="127.0.0.1", port=int(os.getenv("PORT", 8000)), reload=True)