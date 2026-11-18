"""Sample event times preserve dates, source links and existing data."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from inventory_db import connect,initialize
from inventory_service import InventoryService
from demo_tools import populate_demo_data,populate_trend_history,populate_accounting_activity,populate_payroll_activity
from payroll_service import PayrollService


class DemoTimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'test.db';self.svc=InventoryService(self.path)
        self.owner=self.svc.create_user('Owner','owner','OwnerPassword123!','Owner')

    def test_individual_import_times_sources_and_repeat_safety(self):
        populate_demo_data(self.svc,self.owner)
        with closing(connect(self.path)) as db:
            existing=[tuple(r) for r in db.execute('SELECT * FROM "Order" ORDER BY orderID')]
        populate_trend_history(self.svc,self.owner)
        populate_accounting_activity(self.svc,self.owner)
        with closing(connect(self.path)) as db:
            self.assertEqual(existing,[tuple(r) for r in db.execute('SELECT * FROM "Order" ORDER BY orderID LIMIT ?', (len(existing),))])
            times=[r[0][11:19] for r in db.execute('SELECT orderDate FROM "Order"')]
            self.assertNotIn('00:00:00',times);self.assertGreater(len(set(times)),10)
            columns={r[1] for r in db.execute('PRAGMA table_info(AccountingTransaction)')}
            date_col='date' if 'date' in columns else 'transactionDate'
            mismatches=db.execute(f'''SELECT count(*) FROM InventoryTransaction t
                JOIN AccountingTransaction a ON a.sourceType='Order' AND a.sourceID=t.customerOrderID
                WHERE t.transactionDate!=a."{date_col}"''').fetchone()[0]
            self.assertEqual(mismatches,0)
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):populate_trend_history(self.svc,self.owner)
        self.assertEqual(before,self.path.read_bytes())

    def test_payroll_time_is_separate_from_valid_calendar_date(self):
        from user_identity_service import role_id
        employee=self.svc.create_user('Staff','staff','EmployeePassword123!','Employee')
        pay=PayrollService(self.path)
        pay.set_hourly_rate(self.owner,role_id(self.path,employee,'Employee'),20)
        result=populate_payroll_activity(self.svc,self.owner)
        row=pay.payrolls(self.owner)[0]
        self.assertEqual(len(row['payDate']),10)
        self.assertEqual(len(row['payTime']),8);self.assertNotEqual(row['payTime'],'00:00:00')
        self.assertEqual(pay.get_payroll(self.owner,result['payroll_id']).status,'Paid')

    def test_old_payroll_schema_upgrades_repeat_safely(self):
        with closing(connect(self.path)) as db:
            db.execute('ALTER TABLE Payroll DROP COLUMN payTime');db.commit()
        initialize(self.path);initialize(self.path)
        with closing(connect(self.path)) as db:
            self.assertIn('payTime',{r[1] for r in db.execute('PRAGMA table_info(Payroll)')})
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
