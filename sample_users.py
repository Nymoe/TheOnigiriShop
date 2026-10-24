"""Explicit Owner-only import of fictional sample users (main menu option 16).

Contains optional fictional users and profile data. Nothing here
runs at database initialization, launch, or ordinary account registration.
Sample accounts share the current User/Profile/role tables; never overwrite a
real existing user or replace the live SQLite database.

This loader intentionally imports users and profiles only. Loyalty memberships
can be created from menu option 19, once customers choose to enroll.
"""
from __future__ import annotations

from hashlib import pbkdf2_hmac
import secrets
from uuid import uuid4

from inventory_db import transaction
from inventory_service import InventoryError, InventoryService, _ident, _validate_email
from profile_service import _validate_dob, _validate_name, _validate_phone

# Fictional accounts from the supplied sample-user ZIP. For DEMOS ONLY.
DEMO_PASSWORDS = {
    "Owner": "OwnerDemo!2026",
    "Employee": "StaffDemo!2026",
    "Customer": "CustomerDemo!2026",
}

# username, name, role, email, phoneNumber, dateOfBirth
DEMO_USERS = (
    ("akira.owner",    "Akira Tanaka",    "Owner",    "akira.owner@example.test",    "514-555-0101", "1985-04-12"),
    ("emma.staff",     "Emma Laurent",    "Employee", "emma.staff@example.test",     "514-555-0102", "1998-02-18"),
    ("jordan.staff",   "Jordan Kim",      "Employee", "jordan.staff@example.test",   "514-555-0103", "2000-08-07"),
    ("maya.customer",  "Maya Chen",       "Customer", "maya.customer@example.test",  "514-555-0104", "2002-05-23"),
    ("noah.customer",  "Noah Tremblay",   "Customer", "noah.customer@example.test",  "514-555-0105", "1999-11-09"),
    ("olivia.customer","Olivia Martin",   "Customer", "olivia.customer@example.test","514-555-0106", "2001-03-30"),
    ("leo.customer",   "Leo Nguyen",      "Customer", "leo.customer@example.test",   "514-555-0107", "2003-06-14"),
    ("sara.customer",  "Sara Patel",      "Customer", "sara.customer@example.test",  "514-555-0108", "1997-12-03"),
)


def load_sample_users(svc: InventoryService, actor_id: int) -> dict[str, int]:
    """Insert missing demo accounts and profiles, only on an Owner's request.

    All eight records are imported in one transaction, or none.  Existing
    matching sample users are left untouched (including passwords, activity
    status, profile IDs, and edits); conflicting usernames abort the import.
    Running twice never creates duplicates or resets passwords or edited profiles,
    even if an Owner later changes a sample account's username.
    """
    with transaction(svc.db_path) as db:
        actor = db.execute(
            'SELECT role, accountActive, passwordHash FROM "User" WHERE userID=?',
            (_ident(actor_id, "Actor ID"),),
        ).fetchone()
        if not actor or actor["role"] != "Owner" or actor["accountActive"] != 1 or not actor["passwordHash"]:
            raise InventoryError("Only an active Owner can import sample users via option 16.")

        # Keep a stable link to each inserted sample account, because profile
        # details, user names, roles and email addresses can be edited later.
        # A repeat import must not undo those legitimate edits.
        missing = []
        skipped = 0
        for username, name, role, email, phone, dob in DEMO_USERS:
            imported = db.execute('''SELECT u.userID FROM DemoUserImport i
                   JOIN "User" u ON u.userID=i.userID WHERE i.sourceUsername=?''',
                   (username,)).fetchone()
            if imported:
                skipped += 1
                continue
            existing = db.execute('''
                SELECT u.userID,u.name,u.role,u.email,p.userID AS profileUserID
                FROM "User" u LEFT JOIN Profile p ON p.userID=u.userID
                WHERE lower(u.username)=lower(?)
            ''', (username,)).fetchall()
            if existing:
                if (len(existing) != 1 or existing[0]['name'] != name
                        or existing[0]['role'] != role or existing[0]['email'] != email
                        or existing[0]['profileUserID'] is None):
                    raise InventoryError(
                        f"Cannot load samples: username '{username}' is already used by "
                        "a different/incomplete account. No accounts were imported."
                    )
                # An identical account created by an older import can be linked
                # without overwriting any account/profile data.
                db.execute('INSERT INTO DemoUserImport(sourceUsername,userID) VALUES(?,?)',
                           (username, existing[0]['userID']))
                skipped += 1
            else:
                missing.append((username, name, role, email, phone, dob))

        for username, name, role, email, phone, dob in missing:
            # Match InventoryService.create_user() validation, password hashing
            # parameters, subtype linking and 1:1 Profile semantics.
            name = _validate_name(name)
            email = _validate_email(email)
            phone = _validate_phone(phone)
            birth = _validate_dob(dob)
            salt = secrets.token_hex(16)
            hashed = pbkdf2_hmac("sha256", DEMO_PASSWORDS[role].encode("utf-8"),
                                 bytes.fromhex(salt), 220_000).hex()
            user_id = db.execute('''
                INSERT INTO "User"(name,username,role,email,passwordHash,passwordSalt,accountActive)
                VALUES(?,?,?,?,?,?,1)
            ''', (name, username, role, email, hashed, salt)).lastrowid
            if role == "Owner":
                db.execute('INSERT INTO "Owner"(userID) VALUES(?)', (user_id,))
            elif role == "Employee":
                db.execute('INSERT INTO "Employee"(userID,hourlyRate,isActive) VALUES(?,0,1)', (user_id,))
            else:
                db.execute('INSERT INTO "Customer"(userID) VALUES(?)', (user_id,))
            db.execute('''
                INSERT INTO Profile(profileID,userID,name,phoneNumber,dateOfBirth)
                VALUES(?,?,?,?,?)
            ''', (uuid4().hex, user_id, name, phone, birth.isoformat() if birth else None))
            db.execute('INSERT INTO DemoUserImport(sourceUsername,userID) VALUES(?,?)',
                       (username, user_id))

        return {"created": len(missing), "already_present": skipped}
