"""Customer feedback using the Onigiri Shop shared SQLite database.

The existing application's authenticated userID is the actor identifier for
all actions. No second account database, sign-in, or customer creation exists
in this module. Staff may read all feedback; customers may read only their own.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
import sqlite3
from uuid import uuid4

from inventory_db import connect, initialize, transaction


class FeedbackError(ValueError):
    """Validation failure, missing feedback, or denied action."""


class FeedbackStorageError(FeedbackError):
    """Feedback could not be stored; the transaction was rolled back."""


def _actor_id(user_id: int) -> int:
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
        raise FeedbackError('A valid signed-in user is required.')
    return user_id


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise FeedbackError('Feedback text is required.')
    value = value.strip()
    if not value:
        raise FeedbackError('Please complete the feedback text before submitting.')
    if len(value) > 2000 or any(ord(char) < 32 and char not in '\n\t' for char in value):
        raise FeedbackError('Feedback must be 1–2000 characters without control characters.')
    return value


def _rating(value: object) -> int | None:
    if value is None or value == '':
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise FeedbackError('Rating must be a whole number between 1 and 5, or blank.')
    return value


def _user(db: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    row = db.execute('''SELECT userID, role FROM "User"
                        WHERE userID=? AND accountActive=1 AND passwordHash IS NOT NULL''',
                     (_actor_id(user_id),)).fetchone()
    if row is None:
        raise FeedbackError('Your account is no longer active. Please log in again.')
    return row


def _customer_id(db: sqlite3.Connection, user_id: int) -> int:
    actor = _user(db, user_id)
    if actor['role'] != 'Customer':
        raise FeedbackError('Only a Customer can submit feedback or view their own submissions.')
    row = db.execute('SELECT customerID FROM Customer WHERE userID=?', (user_id,)).fetchone()
    if row is None:
        raise FeedbackError('This account is missing its Customer profile. Ask an Owner to check your Customer account in option 20 (Manage users).')
    return row['customerID']


def _staff(db: sqlite3.Connection, user_id: int) -> None:
    actor = _user(db, user_id)
    if actor['role'] not in ('Employee', 'Owner'):
        raise FeedbackError('Only an Employee or Owner can review customer feedback.')


def _feedback_id(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise FeedbackError('Feedback ID must be a positive whole number.')
    return value


@dataclass(frozen=True)
class Feedback:
    """Feedback record submitted by a registered customer."""

    feedbackID: int | None
    customerID: int
    feedbackText: str
    submissionDate: str | None = None
    status: str = 'Submitted'
    rating: int | None = None
    publicUUID: str | None = None
    customerName: str | None = None
    customerUsername: str | None = None

    def validateFeedback(self) -> bool:
        """Validate the required text and optional rating."""
        _text(self.feedbackText)
        _rating(self.rating)
        return True

    def getFeedback(self) -> str:
        return self.feedbackText

    def updateStatus(self, new_status: str) -> 'Feedback':
        """Produce a new model; only FeedbackService can persist a status change."""
        if new_status not in ('Submitted', 'Reviewed'):
            raise FeedbackError('Status must be Submitted or Reviewed.')
        return replace(self, status=new_status)

    def storeFeedback(self, service: 'FeedbackService', actor_user_id: int) -> 'Feedback':
        """Delegate storage to the service, which verifies the actor/customer link."""
        self.validateFeedback()
        with closing(connect(service.db_path)) as db:
            if _customer_id(db, actor_user_id) != self.customerID:
                raise FeedbackError('This feedback belongs to a different Customer account.')
        return service.submit_feedback(actor_user_id, self.feedbackText, self.rating)


class FeedbackService:
    """Submit feedback and manage staff review permissions."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = db_path
        initialize(db_path)

    @staticmethod
    def _row(row: sqlite3.Row) -> Feedback:
        return Feedback(
            feedbackID=row['feedbackID'], customerID=row['customerID'],
            feedbackText=row['feedbackText'], submissionDate=row['submissionDate'],
            status=row['status'], rating=row['rating'], publicUUID=row['publicUUID'],
            customerName=row['customerName'] if 'customerName' in row.keys() else None,
            customerUsername=row['customerUsername'] if 'customerUsername' in row.keys() else None,
        )

    def submit_feedback(self, actor_user_id: int, feedback_text: str,
                        rating: int | None = None) -> Feedback:
        """Validate then save atomically; only a signed-in Customer can submit."""
        actor_user_id = _actor_id(actor_user_id)
        text = _text(feedback_text)
        rating = _rating(rating)
        try:
            with transaction(self.db_path) as db:
                customer_id = _customer_id(db, actor_user_id)
                row_id = db.execute('''
                    INSERT INTO Feedback(publicUUID, customerID, feedbackText,
                                         rating, submissionDate, status)
                    VALUES(?, ?, ?, ?, ?, 'Submitted')
                ''', (uuid4().hex, customer_id, text, rating,
                      datetime.now().astimezone().isoformat(timespec='seconds'))).lastrowid
                saved = db.execute('SELECT * FROM Feedback WHERE feedbackID=?', (row_id,)).fetchone()
                return self._row(saved)
        except sqlite3.Error as exc:
            raise FeedbackStorageError('Feedback could not be saved. Please try again.') from exc

    def view_submitted_feedback(self, actor_user_id: int) -> list[Feedback]:
        """Customer may see their submissions only, including review status."""
        with closing(connect(self.db_path)) as db:
            customer_id = _customer_id(db, actor_user_id)
            rows = db.execute('''SELECT f.*, u.name AS customerName,
                                       u.username AS customerUsername
                                 FROM Feedback f
                                 JOIN Customer c ON c.customerID=f.customerID
                                 JOIN "User" u ON u.userID=c.userID
                                 WHERE f.customerID=? ORDER BY f.feedbackID DESC''',
                              (customer_id,)).fetchall()
            return [self._row(row) for row in rows]

    def view_feedback(self, actor_user_id: int, feedback_id: int | None = None,
                      *, status: str | None = None) -> list[Feedback]:
        """Staff-only list/detail with optional status filter."""
        if status is not None and status not in ('Submitted', 'Reviewed'):
            raise FeedbackError('Status must be Submitted or Reviewed.')
        if feedback_id is not None:
            feedback_id = _feedback_id(feedback_id)
        with closing(connect(self.db_path)) as db:
            _staff(db, actor_user_id)
            sql = '''SELECT f.*, u.name AS customerName, u.username AS customerUsername
                       FROM Feedback f JOIN Customer c ON c.customerID=f.customerID
                       JOIN "User" u ON u.userID=c.userID WHERE 1=1'''
            params: list[object] = []
            if feedback_id is not None:
                sql += ' AND f.feedbackID=?'
                params.append(feedback_id)
            if status is not None:
                sql += ' AND f.status=?'
                params.append(status)
            sql += ' ORDER BY f.feedbackID DESC'
            return [self._row(row) for row in db.execute(sql, params)]

    def review_feedback(self, actor_user_id: int, feedback_id: int) -> Feedback:
        """Mark a stored record Reviewed after staff selects it for review."""
        return self.update_status(actor_user_id, feedback_id, 'Reviewed')

    def update_status(self, actor_user_id: int, feedback_id: int,
                      status: str) -> Feedback:
        feedback_id = _feedback_id(feedback_id)
        if status not in ('Submitted', 'Reviewed'):
            raise FeedbackError('Status must be Submitted or Reviewed.')
        with transaction(self.db_path) as db:
            _staff(db, actor_user_id)
            current = db.execute('SELECT * FROM Feedback WHERE feedbackID=?',
                                 (feedback_id,)).fetchone()
            if current is None:
                raise FeedbackError(f'Feedback #{feedback_id} was not found.')
            db.execute('UPDATE Feedback SET status=? WHERE feedbackID=?', (status, feedback_id))
            return self._row(db.execute('SELECT * FROM Feedback WHERE feedbackID=?',
                                        (feedback_id,)).fetchone())

    # Compatibility aliases for callers using camelCase method names.
    def submitFeedback(self, actor_user_id: int, feedback_text: str,
                       rating: int | None = None) -> Feedback:
        return self.submit_feedback(actor_user_id, feedback_text, rating)

    def viewSubmittedFeedback(self, actor_user_id: int) -> list[Feedback]:
        return self.view_submitted_feedback(actor_user_id)

    def viewFeedback(self, actor_user_id: int, feedback_id: int | None = None) -> list[Feedback]:
        return self.view_feedback(actor_user_id, feedback_id)

    def reviewFeedback(self, actor_user_id: int, feedback_id: int) -> Feedback:
        return self.review_feedback(actor_user_id, feedback_id)

    def storeFeedback(self, actor_user_id: int, feedback_text: str,
                      rating: int | None = None) -> Feedback:
        return self.submit_feedback(actor_user_id, feedback_text, rating)

    def getFeedback(self, actor_user_id: int, feedback_id: int) -> Feedback:
        rows = self.view_feedback(actor_user_id, feedback_id)
        if not rows:
            raise FeedbackError(f'Feedback #{feedback_id} was not found.')
        return rows[0]

    def updateStatus(self, actor_user_id: int, feedback_id: int, status: str) -> Feedback:
        return self.update_status(actor_user_id, feedback_id, status)
