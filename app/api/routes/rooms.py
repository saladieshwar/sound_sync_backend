from fastapi import APIRouter, BackgroundTasks, status

from app.api.deps import CurrentUser, DbSession
from app.realtime import sync_facade
from app.realtime.events import EventType
from app.schemas.common import ErrorResponse, MessageResponse
from app.schemas.room import RoomCreateRequest, RoomOut, TransferAccessRequest
from app.services import room_service

router = APIRouter(prefix="/rooms", tags=["rooms"])

_errors = {403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 410: {"model": ErrorResponse}}


@router.post("", response_model=RoomOut, status_code=status.HTTP_201_CREATED)
def create_room(body: RoomCreateRequest, user: CurrentUser, db: DbSession):
    room = room_service.create_room(db, name=body.name, admin_user_id=user.id)
    return room_service.to_room_out(room)


@router.get("/{room_id}", response_model=RoomOut, responses=_errors)
def get_room(room_id: str, user: CurrentUser, db: DbSession):
    room = room_service.get_active_room_or_404(db, room_id)
    room_service.require_participant(db, room, user.id)
    return room_service.to_room_out(room)


@router.post("/{room_id}/join", response_model=RoomOut, responses=_errors)
def join_room(room_id: str, user: CurrentUser, db: DbSession):
    room = room_service.join_room(db, room_id, user.id)
    return room_service.to_room_out(room)


@router.post("/{room_id}/leave", response_model=MessageResponse, responses=_errors)
def leave_room(room_id: str, user: CurrentUser, db: DbSession, tasks: BackgroundTasks):
    room, closed = room_service.leave_room(db, room_id, user.id)
    if closed:
        tasks.add_task(sync_facade.close_room, room.id)
        return MessageResponse(message="Room closed")
    tasks.add_task(sync_facade.remove_user, room.id, user.id)
    tasks.add_task(
        sync_facade.broadcast,
        room.id,
        EventType.USER_LEFT,
        {"user_id": user.id, "reason": "left", "controller_user_id": room.controller_user_id},
        user.id,
    )
    return MessageResponse(message="Left room")


@router.post("/{room_id}/transfer-access", response_model=RoomOut, responses=_errors)
def transfer_access(
    room_id: str,
    body: TransferAccessRequest,
    user: CurrentUser,
    db: DbSession,
    tasks: BackgroundTasks,
):
    room = room_service.transfer_access(
        db, room_id, requester_id=user.id, target_user_id=body.target_user_id
    )
    tasks.add_task(
        sync_facade.broadcast,
        room.id,
        EventType.ACCESS_TRANSFER,
        {"controller_user_id": room.controller_user_id},
        user.id,
    )
    return room_service.to_room_out(room)
