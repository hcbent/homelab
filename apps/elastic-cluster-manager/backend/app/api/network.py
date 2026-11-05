from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, auth
from app.db import get_db
from app.desired.network import NetworkProfile
from app.models import NetworkProfileRow, User
from app.network_profiles import addresses_in_use, conflicts_in_range, to_domain

router = APIRouter(prefix="/api/network-profiles", tags=["network"],
                   dependencies=[Depends(auth.require_csrf_header)])


def _out(row: NetworkProfileRow, in_use: list[dict]) -> dict:
    profile = to_domain(row)
    return {
        "id": row.id, **profile.model_dump(),
        "pool_size": profile.pool_size,
        # addresses already used inside the range: a warning for the user, allocation skips them anyway
        "in_use_in_range": conflicts_in_range(profile, in_use),
    }


@router.get("")
def list_profiles(db: Session = Depends(get_db), _: User = Depends(auth.current_user)):
    in_use = addresses_in_use(db)
    return [_out(r, in_use) for r in db.scalars(select(NetworkProfileRow).order_by(NetworkProfileRow.name))]


@router.post("", status_code=201)
def create_profile(body: NetworkProfile, db: Session = Depends(get_db),
                   user: User = Depends(auth.current_user)):
    if db.scalar(select(NetworkProfileRow).where(NetworkProfileRow.name == body.name)):
        raise HTTPException(409, "A network profile with that name exists")
    row = NetworkProfileRow(**body.model_dump())
    db.add(row)
    db.commit()
    audit.record(db, user.username, "network_profile.create", "network_profile", row.id, name=row.name,
                 range=f"{row.range_start}-{row.range_end}")
    return _out(row, addresses_in_use(db))


@router.put("/{profile_id}")
def update_profile(profile_id: str, body: NetworkProfile, db: Session = Depends(get_db),
                   user: User = Depends(auth.current_user)):
    row = db.get(NetworkProfileRow, profile_id)
    if not row:
        raise HTTPException(404, "Not found")
    clash = db.scalar(select(NetworkProfileRow).where(
        NetworkProfileRow.name == body.name, NetworkProfileRow.id != profile_id))
    if clash:
        raise HTTPException(409, "A network profile with that name exists")
    before = f"{row.range_start}-{row.range_end}"
    for field, value in body.model_dump().items():
        setattr(row, field, value)
    db.commit()
    audit.record(db, user.username, "network_profile.update", "network_profile", row.id, name=row.name,
                 range_before=before, range_after=f"{row.range_start}-{row.range_end}")
    return _out(row, addresses_in_use(db))
