"""Translate user-facing account IDs without changing stored role identities."""
from contextlib import closing
from inventory_db import connect
from inventory_service import InventoryError, _ident


def role_id(db_path, user_id, role):
    if role not in ('Customer','Employee'):raise InventoryError('Unsupported account type.')
    with closing(connect(db_path)) as db:
        row=db.execute(f'''SELECT r.{role.lower()}ID AS id FROM "User" u
            JOIN "{role}" r ON r.userID=u.userID WHERE u.userID=? AND u.role=?''',
            (_ident(user_id,'User ID'),role)).fetchone()
        if row is None:raise InventoryError(f'User #{user_id} is not a {role} account. Choose a {role} User ID.')
        return row['id']


def user_id_for_role(db_path, subtype_id, role):
    with closing(connect(db_path)) as db:
        row=db.execute(f'SELECT userID FROM "{role}" WHERE {role.lower()}ID=?',
                       (subtype_id,)).fetchone()
        return row['userID'] if row else None
