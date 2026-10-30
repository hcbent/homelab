from sqlalchemy.orm import Session

from app.crypto import redact
from app.models import AuditEvent


def record(db: Session, actor: str, action: str, target_type: str | None = None,
           target_id: str | None = None, **details) -> None:
    safe = {k: redact(v) if isinstance(v, str) else v for k, v in details.items()}
    db.add(AuditEvent(actor=actor, action=action, target_type=target_type,
                      target_id=target_id, details=safe))
    db.commit()
