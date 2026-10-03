from fastapi import APIRouter

from app.api.routes import admin, auth, health, library, rooms, songs
from app.realtime import ws_routes

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(songs.router)
api_router.include_router(library.router)
api_router.include_router(rooms.router)
api_router.include_router(admin.router)
api_router.include_router(ws_routes.router)
