"""Fábrica de rotas CRUD para cadastros simples (salas, categorias, contas...).

Sem `from __future__ import annotations`: o FastAPI precisa das anotações já avaliadas
(os schemas são variáveis da closure)."""
import uuid
from typing import Any, Callable

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.database import get_db
from app.core.deps import require_any
from app.core.errors import Conflict, NotFound
from app.models.auth import User


def make_crud(
    router: APIRouter,
    *,
    path: str,
    model: type,
    schema_in: type[BaseModel],
    schema_out: type[BaseModel],
    read_perms: tuple[str, ...],
    write_perms: tuple[str, ...],
    entity: str,
    order_by: Any = None,
    validate: Callable[[Session, dict, Any], None] | None = None,
) -> None:
    name = path.strip("/").replace("-", "_").replace("/", "_")

    def list_items(
        active: bool | None = None, db: Session = Depends(get_db), user: User = Depends(require_any(*read_perms))
    ):
        stmt = select(model)
        if active is not None and hasattr(model, "is_active"):
            stmt = stmt.where(model.is_active == active)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        return db.scalars(stmt).all()

    def create_item(data: schema_in, db: Session = Depends(get_db), user: User = Depends(require_any(*write_perms))):  # type: ignore[valid-type]
        values = data.model_dump()
        if validate:
            validate(db, values, None)
        obj = model(**values)
        db.add(obj)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise Conflict("Já existe um registro com esses dados.") from exc
        audit(db, f"{entity}_criado", user=user, entity=entity, entity_id=obj.id, details=values)
        db.commit()
        db.refresh(obj)
        return obj

    def update_item(
        item_id: uuid.UUID, data: schema_in, db: Session = Depends(get_db), user: User = Depends(require_any(*write_perms))  # type: ignore[valid-type]
    ):
        obj = db.get(model, item_id)
        if obj is None:
            raise NotFound()
        values = data.model_dump()
        if validate:
            validate(db, values, obj)
        for k, v in values.items():
            setattr(obj, k, v)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise Conflict("Já existe um registro com esses dados.") from exc
        audit(db, f"{entity}_alterado", user=user, entity=entity, entity_id=obj.id, details=values)
        db.commit()
        db.refresh(obj)
        return obj

    def delete_item(item_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_any(*write_perms))):
        obj = db.get(model, item_id)
        if obj is None:
            raise NotFound()
        try:
            db.delete(obj)
            db.flush()
            audit(db, f"{entity}_excluido", user=user, entity=entity, entity_id=item_id)
            db.commit()
            return {"message": "Registro excluído."}
        except IntegrityError:
            db.rollback()
            obj = db.get(model, item_id)
            if hasattr(obj, "is_active"):
                obj.is_active = False
                audit(db, f"{entity}_inativado", user=user, entity=entity, entity_id=item_id)
                db.commit()
                return {"message": "Registro em uso: foi inativado em vez de excluído."}
            raise Conflict("Registro em uso por outros cadastros; não pode ser excluído.")

    router.add_api_route(path, list_items, methods=["GET"], response_model=list[schema_out], name=f"list_{name}")
    router.add_api_route(path, create_item, methods=["POST"], response_model=schema_out, status_code=201, name=f"create_{name}")
    router.add_api_route(path + "/{item_id}", update_item, methods=["PUT"], response_model=schema_out, name=f"update_{name}")
    router.add_api_route(path + "/{item_id}", delete_item, methods=["DELETE"], name=f"delete_{name}")
