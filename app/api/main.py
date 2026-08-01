from fastapi import APIRouter

from app.core.config import settings

api_router = APIRouter()

if settings.ENVIRONMENT == 'dev':
    # This is a place to put all the dev-oriented routes, such as testing endpoints, debug routes, etc.
    pass