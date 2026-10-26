"""Profile management for the shared Onigiri Shop system.

The authenticated application supplies its CURRENT userID; no separate identity,
login store, loyalty balance, or payroll details are managed here. The service is
UI-independent so other modules can reuse the same profile records.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
import re
import sqlite3
from typing import Mapping

from inventory_db import connect, initialize, transaction


class ProfileError(ValueError):
    """A profile was unavailable, invalid, or could not be updated."""


class ProfileNotFoundError(ProfileError):
    """The user's profile does not exist."""


class ProfileConflictError(ProfileError):
    """The displayed profile has changed since it was opened."""


_EDITABLE_FIELDS = frozenset({'name', 'email', 'phoneNumber', 'dateOfBirth'})
_PHONE_CHARS = re.compile(r'^[+\d\s().-]+$')


def _valid_user_id(user_id: int) -> int:
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ProfileError('A valid signed-in user is required.')
    return user_id


def _validate_name(raw: object) -> str:
    if not isinstance(raw, str):
        raise ProfileError('Name must be text.')
    name = raw.strip()
    if not name:
        raise ProfileError('Name is required.')
    if len(name) > 120 or any(ord(c) < 32 for c in name):
        raise ProfileError('Name must be at most 120 characters without control characters.')
    return name


def _validate_phone(raw: object) -> str | None:
    if raw is None or raw == '':
        return None
    if not isinstance(raw, str):
        raise ProfileError('Phone number must be text.')
    phone = raw.strip()
    if not phone:
        return None
    digits = sum(c.isdigit() for c in phone)
    if len(phone) > 25 or not 7 <= digits <= 15 or not _PHONE_CHARS.fullmatch(phone):
        raise ProfileError('Phone number must contain 7–15 digits and valid punctuation.')
    return phone


def _validate_email(raw: object) -> str | None:
    """Email is a shared User field, editable through the user's own profile.

    Match the account-creation rules without importing inventory_service,
    which itself imports profile_service.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ProfileError('Email must be text.')
    email = raw.strip() or None
    if email and (len(email) > 254 or email.count('@') != 1 or
                  any(c.isspace() or ord(c) < 32 for c in email) or
                  not all(email.split('@')) or '.' not in email.split('@')[1]):
        raise ProfileError('Enter a valid email address, or clear the email field.')
    return email


def _validate_dob(raw: object) -> date | None:
    if raw is None or raw == '':
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        birthday = raw
    elif isinstance(raw, str):
        try:
            birthday = date.fromisoformat(raw)
        except ValueError as exc:
            raise ProfileError('Date of birth must be a real date in YYYY-MM-DD format.') from exc
        if birthday.isoformat() != raw:
            raise ProfileError('Date of birth must use YYYY-MM-DD format.')
    else:
        raise ProfileError('Date of birth must be YYYY-MM-DD.')
    if birthday > date.today():
        raise ProfileError('Date of birth cannot be in the future.')
    return birthday


@dataclass(frozen=True)
class Profile:
    """P-01 concrete domain class; one Profile belongs to one shared User."""

    profile_id: str
    user_id: int
    name: str
    phone_number: str | None
    date_of_birth: date | None
    version: int
    username: str
    role: str
    email: str | None

    def validate_changes(self, changes: Mapping[str, object]) -> 'Profile':
        """Validate editable data without touching stored state."""
        unknown = set(changes) - _EDITABLE_FIELDS
        if unknown:
            raise ProfileError('Only name, email, phoneNumber and dateOfBirth may be edited.')
        if not changes:
            raise ProfileError('No profile changes were submitted.')
        return replace(
            self,
            name=_validate_name(changes['name']) if 'name' in changes else self.name,
            email=_validate_email(changes['email']) if 'email' in changes else self.email,
            phone_number=_validate_phone(changes['phoneNumber'])
            if 'phoneNumber' in changes else self.phone_number,
            date_of_birth=_validate_dob(changes['dateOfBirth'])
            if 'dateOfBirth' in changes else self.date_of_birth,
        )

    # Persistence belongs to ProfileService; this model validates candidate changes.
    def update_profile(self, changes: Mapping[str, object]) -> 'Profile':
        return self.validate_changes(changes)


class ProfileService:
    """Retrieve, validate, and atomically update the current actor's profile.

    Callers must use the userID from an authenticated session (InventoryService.login)
    rather than an ID taken from a request or an input prompt. A future HTTP API must
    enforce the same trusted-session boundary.
    """

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = db_path
        initialize(db_path)

    @staticmethod
    def _fetch(db: sqlite3.Connection, user_id: int) -> Profile:
        row = db.execute('''
            SELECT p.profileID, p.userID, p.name, p.phoneNumber, p.dateOfBirth,
                   p.version, u.username, u.role, u.email
            FROM Profile p JOIN "User" u ON u.userID=p.userID
            WHERE p.userID=?
        ''', (user_id,)).fetchone()
        if row is None:
            raise ProfileNotFoundError('Profile not found. No information was changed.')
        return Profile(
            profile_id=row['profileID'], user_id=row['userID'], name=row['name'],
            phone_number=row['phoneNumber'],
            date_of_birth=date.fromisoformat(row['dateOfBirth']) if row['dateOfBirth'] else None,
            version=row['version'], username=row['username'], role=row['role'], email=row['email'],
        )

    def view_profile(self, current_user_id: int) -> Profile:
        """Return the signed-in user's profile without changing stored data."""
        current_user_id = _valid_user_id(current_user_id)
        with closing(connect(self.db_path)) as db:
            return self._fetch(db, current_user_id)

    def update_profile(self, current_user_id: int, changes: Mapping[str, object],
                       *, expected_version: int | None = None) -> Profile:
        """Validate and update profile data and shared User details together.

        When expected_version is supplied (as it is by the CLI), stale forms
        cannot silently overwrite someone else's newer changes. SQLite's
        transaction guarantees no partial update on an error.
        """
        current_user_id = _valid_user_id(current_user_id)
        if not isinstance(changes, Mapping):
            raise ProfileError('Profile changes must be provided as field/value pairs.')
        if expected_version is not None and (isinstance(expected_version, bool)
                                             or not isinstance(expected_version, int)
                                             or expected_version < 0):
            raise ProfileError('Invalid profile version.')
        with transaction(self.db_path) as db:
            existing = self._fetch(db, current_user_id)
            if expected_version is not None and existing.version != expected_version:
                raise ProfileConflictError('Profile changed since you opened it. View it again before editing.')
            updated = existing.update_profile(changes)
            db.execute('''
                UPDATE Profile SET name=?, phoneNumber=?, dateOfBirth=?, version=version+1
                WHERE userID=?
            ''', (updated.name, updated.phone_number,
                  updated.date_of_birth.isoformat() if updated.date_of_birth else None,
                  current_user_id))
            # Other modules and the current login screen already read User.name.
            # Keep it consistent with the profile in the same transaction.
            db.execute('UPDATE "User" SET name=?,email=? WHERE userID=?',
                       (updated.name, updated.email, current_user_id))
            return self._fetch(db, current_user_id)
