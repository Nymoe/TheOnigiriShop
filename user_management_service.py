"""Owner-only account administration, separate from Use Case 5 self-service profiles.

All operations use the shared User / Profile / role subtype tables. The actor ID
must come from an authenticated session, never an arbitrary form field. Database
role and active status are rechecked on *every* call (including reads).
"""
from __future__ import annotations

from hashlib import pbkdf2_hmac
import secrets
import sqlite3
from pathlib import Path
from typing import Mapping

from inventory_db import connect, initialize, transaction
from inventory_service import InventoryError, InventoryService, _ident, _validate_email
from profile_service import _validate_name, _validate_phone, _validate_dob

ROLES = frozenset({'Owner', 'Employee', 'Customer'})


def _owner(db: sqlite3.Connection, actor_id: int) -> None:
    actor = db.execute('''SELECT role, accountActive, passwordHash FROM "User"
                          WHERE userID=?''', (_ident(actor_id, 'Actor ID'),)).fetchone()
    if not actor or actor['role'] != 'Owner' or actor['accountActive'] != 1 or not actor['passwordHash']:
        raise InventoryError('Only an active Owner can manage user accounts.')


def _account(db: sqlite3.Connection, target_id: int):
    user = db.execute('''SELECT u.userID, u.name, u.username, u.email, u.role,
                        u.accountActive, p.profileID, p.phoneNumber, p.dateOfBirth
                        FROM "User" u LEFT JOIN Profile p ON p.userID=u.userID
                        WHERE u.userID=?''', (_ident(target_id, 'User ID'),)).fetchone()
    if user is None:
        raise InventoryError(f'User #{target_id} was not found.')
    return user


def _protect_owner(db: sqlite3.Connection, actor_id: int, target_id: int) -> None:
    """Do not demote, disable or delete a signed-in owner or the final owner."""
    target = _account(db, target_id)
    if target_id == actor_id:
        raise InventoryError('You cannot remove your own Owner access. Use My Profile to edit your details.')
    if target['role'] == 'Owner' and target['accountActive']:
        count = db.execute('''SELECT COUNT(*) FROM "User" WHERE role='Owner' AND
                              accountActive=1 AND passwordHash IS NOT NULL''').fetchone()[0]
        if count <= 1:
            raise InventoryError('The system must retain at least one active Owner account.')


class UserManagementService:
    """Account lifecycle for authorised owners; UI agnostic for future integration."""
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = db_path
        initialize(db_path)

    def list_accounts(self, actor_id: int) -> list[dict]:
        db = connect(self.db_path)
        try:
            _owner(db, actor_id)
            return [dict(row) for row in db.execute('''
                SELECT userID, name, username, role,
                       CASE WHEN accountActive=1 THEN 'Active' ELSE 'Disabled' END AS status
                FROM "User" ORDER BY userID
            ''')]
        finally:
            db.close()

    def get_account(self, actor_id: int, target_id: int) -> dict:
        db = connect(self.db_path)
        try:
            _owner(db, actor_id)
            return dict(_account(db, target_id))
        finally:
            db.close()

    def create_account(self, actor_id: int, name: str, username: str, password: str,
                       role: str = 'Employee', email: str | None = None,
                       phone_number: str | None = None,
                       date_of_birth: str | None = None) -> int:
        with transaction(self.db_path) as db:
            _owner(db, actor_id)
        # Existing account creation retains its shared Profile and subtype logic.
        return InventoryService(self.db_path).create_user(
            name, username, password, role, email=email, phone_number=phone_number,
            date_of_birth=date_of_birth)

    def edit_account(self, actor_id: int, target_id: int, changes: Mapping[str, str]) -> dict:
        """Change basic user + profile fields together, or commit none of them."""
        allowed = {'name', 'username', 'email', 'phoneNumber', 'dateOfBirth'}
        if not changes or set(changes) - allowed:
            raise InventoryError('Choose at least one editable field: name, username, email, phone, birth date.')
        with transaction(self.db_path) as db:
            _owner(db, actor_id)
            current = _account(db, target_id)
            name = _validate_name(changes['name']) if 'name' in changes else current['name']
            username = current['username']
            if 'username' in changes:
                raw = changes['username']
                if not isinstance(raw, str) or not raw.strip() or len(raw.strip()) > 64 or any(c.isspace() or ord(c) < 32 for c in raw.strip()):
                    raise InventoryError('Username must be 1–64 characters without spaces.')
                username = raw.strip()
                duplicate = db.execute('''SELECT 1 FROM "User" WHERE lower(username)=lower(?)
                                          AND userID<>?''', (username, target_id)).fetchone()
                if duplicate:
                    raise InventoryError('That username is already in use.')
            email = (_validate_email(changes['email']) if 'email' in changes
                     else current['email'])
            phone = (_validate_phone(changes['phoneNumber']) if 'phoneNumber' in changes
                     else current['phoneNumber'])
            dob = (_validate_dob(changes['dateOfBirth']) if 'dateOfBirth' in changes
                   else _validate_dob(current['dateOfBirth']))
            if current['profileID'] is None:
                raise InventoryError('Profile record is missing. No changes were saved.')
            db.execute('UPDATE "User" SET name=?,username=?,email=? WHERE userID=?',
                       (name, username, email, target_id))
            db.execute('''UPDATE Profile SET name=?,phoneNumber=?,dateOfBirth=?,version=version+1
                          WHERE userID=?''', (name, phone, dob.isoformat() if dob else None, target_id))
            return dict(_account(db, target_id))

    def change_role(self, actor_id: int, target_id: int, new_role: str) -> None:
        new_role = new_role.title()
        if new_role not in ROLES:
            raise InventoryError('Role must be Owner, Employee or Customer.')
        with transaction(self.db_path) as db:
            _owner(db, actor_id)
            current = _account(db, target_id)
            if current['role'] == new_role:
                return
            if current['role'] == 'Owner':
                _protect_owner(db, actor_id, target_id)
            # Deleting former subtype is safe only when no other team table
            # references it; FK errors abort the entire role change.
            subtype = current['role']
            if subtype in ROLES:
                db.execute(f'DELETE FROM "{subtype}" WHERE userID=?', (target_id,))
            if new_role == 'Owner':
                db.execute('INSERT INTO "Owner"(userID) VALUES(?)', (target_id,))
            elif new_role == 'Employee':
                db.execute('''INSERT INTO "Employee"(userID,hourlyRate,isActive)
                              VALUES(?,0,1)''', (target_id,))
            else:
                db.execute('INSERT INTO "Customer"(userID) VALUES(?)', (target_id,))
            db.execute('UPDATE "User" SET role=? WHERE userID=?', (new_role, target_id))

    def reset_password(self, actor_id: int, target_id: int, new_password: str) -> None:
        if not isinstance(new_password, str) or len(new_password) < 8:
            raise InventoryError('New password must contain at least eight characters.')
        with transaction(self.db_path) as db:
            _owner(db, actor_id)
            _account(db, target_id)
            salt = secrets.token_hex(16)
            digest = pbkdf2_hmac('sha256', new_password.encode('utf-8'), bytes.fromhex(salt), 220_000).hex()
            db.execute('UPDATE "User" SET passwordHash=?,passwordSalt=? WHERE userID=?',
                       (digest, salt, target_id))

    def set_active(self, actor_id: int, target_id: int, active: bool) -> None:
        if not isinstance(active, bool):
            raise InventoryError('Account status must be enabled or disabled.')
        with transaction(self.db_path) as db:
            _owner(db, actor_id)
            current = _account(db, target_id)
            if not active:
                _protect_owner(db, actor_id, target_id)
            if bool(current['accountActive']) == active:
                return
            db.execute('UPDATE "User" SET accountActive=? WHERE userID=?', (int(active), target_id))

    def delete_account(self, actor_id: int, target_id: int) -> None:
        """Permanently delete only unreferenced accounts; preserve business history."""
        with transaction(self.db_path) as db:
            _owner(db, actor_id)
            current = _account(db, target_id)
            _protect_owner(db, actor_id, target_id)
            # Older inventory records refer to User.userID without declaring
            # foreign keys. Do not orphan those references during deletion.
            for table, column in (('Order', 'createdByUserID'),
                                  ('InventoryTransaction', 'userID')):
                if db.execute(f'SELECT 1 FROM "{table}" WHERE "{column}"=? LIMIT 1',
                              (target_id,)).fetchone():
                    raise InventoryError('User has related business records and cannot be deleted. '
                                         'Disable the account instead to preserve history.')
            try:
                # FKs from every module remain enforced by SQLite.
                db.execute('DELETE FROM Profile WHERE userID=?', (target_id,))
                for table in ('Owner', 'Employee', 'Customer'):
                    db.execute(f'DELETE FROM "{table}" WHERE userID=?', (target_id,))
                db.execute('DELETE FROM "User" WHERE userID=?', (target_id,))
            except sqlite3.IntegrityError as exc:
                raise InventoryError('User has related business records and cannot be deleted. '
                                     'Disable the account instead to preserve history.') from exc
