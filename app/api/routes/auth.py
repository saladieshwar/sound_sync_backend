from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.schemas.common import ErrorResponse
from app.schemas.user import UserOut
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}},
)
def register(body: RegisterRequest, db: DbSession):
    return auth_service.register(
        db, username=body.username, email=body.email, password=body.password
    )


@router.post("/login", response_model=TokenResponse, responses={401: {"model": ErrorResponse}})
def login(body: LoginRequest, db: DbSession):
    token, user = auth_service.login(db, email=body.email, password=body.password)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut, responses={401: {"model": ErrorResponse}})
def me(user: CurrentUser):
    return user
