from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class ChatRequest(BaseModel):
    message: str


@router.post("/chat")
async def chat(request: Request, body: ChatRequest):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message must not be empty")

    from app.chat import process_chat

    cache = request.app.state.cache
    market_source = request.app.state.market_source
    result = await process_chat(
        message=body.message,
        cache=cache,
        market_source=market_source,
    )
    return result
