import os
from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookParser
from dotenv import load_dotenv
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent
)

#Import config.py from .env
from config import LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET

app = FastAPI()

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
parser = WebhookParser(channel_secret=LINE_CHANNEL_SECRET)

@app.post("/callback")
async def callback(request: Request):
    # Signature from Line Header
    signature = request.headers.get("X-Line-Signature", "")

    # Đọc nội dung body từ request
    body = await request.body()
    body_str = body.decode("utf-8")

    try:
        # analyze the webhook events
        events = parser.parse(body_str, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature. Please check your channel secret.")

    for event in events:
        # Check if the event is a text message from the user
        if isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
            reply_token = event.reply_token

            #  (Mock response)
            bot_response = "Hi Guys. We are still in testing phase."

            # Gửi phản hồi lại cho người dùng qua LINE Messaging API
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=reply_token,
                        messages=[TextMessage(text=bot_response)]
                    )
                )
                
    return "OK"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)