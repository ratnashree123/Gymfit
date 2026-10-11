"""/api/auth: login, logout, current user, change password."""
from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.common import get_client_ip
from app.models import User
from app.schemas.auth import ChangePasswordIn, MessageOut, TokenOut, UserOut
from app.security import create_access_token
from app.services import auth_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenOut)
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Log in with email (put it in the 'username' field) and password."""
    user = auth_service.authenticate(db, form.username, form.password, get_client_ip(request))
    token, expires_in = create_access_token(user.id, user.role.name)
    return TokenOut(access_token=token, expires_in=expires_in, user=UserOut.from_user(user))


@router.get("/me", response_model=UserOut)
def read_current_user(user: User = Depends(get_current_user)):
    return UserOut.from_user(user)


@router.post("/logout", response_model=MessageOut)
def logout(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Tokens are stateless, so the browser must delete its copy. This records the logout."""
    log_action(db, user_id=user.id, action="auth.logout", entity_type="user",
               entity_id=user.id, ip=get_client_ip(request))
    db.commit()
    return MessageOut(message="Logged out")


@router.post("/change-password", response_model=MessageOut)
def change_password(
    payload: ChangePasswordIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    auth_service.change_password(db, user, payload.current_password, payload.new_password,
                                 get_client_ip(request))
    return MessageOut(message="Password changed")
