"""Read-only record views and supplier catalogue updates for desktop workflows."""
from contextlib import closing
import math
from inventory_db import connect,transaction
from inventory_service import InventoryService,InventoryError,_ident


class DetailService:
    def __init__(self,path):self.path=path

    def rows(self,sql,args=()):
        with closing(connect(self.path)) as db:
            return [dict(r) for r in db.execute(sql,args)]

    def recipe(self,rid):
        rows=self.rows('''SELECT ri.ingredientID,i.ingredientName,i.unit,ri.quantityRequired,i.quantityOnHand
            FROM RecipeIngredient ri JOIN InventoryItem i ON i.ingredientID=ri.ingredientID WHERE recipeID=?''',(rid,))
        return rows,min((math.floor(r['quantityOnHand']/r['quantityRequired']) for r in rows),default=None)

    def purchase(self,pid):
        rows=self.rows('''SELECT io.*,s.name AS supplier FROM InventoryOrder io
            LEFT JOIN Supplier s ON s.supplierID=io.supplierID WHERE inventoryOrderID=?''',(pid,))
        if not rows:raise InventoryError('Purchase order not found.')
        lines=InventoryService(self.path).purchase_order_lines(pid)
        summary=rows[0]
        summary['supplier']=summary['supplier'] or 'Not recorded'
        delivered=self.rows('''SELECT DISTINCT s.name FROM Supplier s JOIN InventoryTransaction t
            ON t.supplierID=s.supplierID WHERE t.inventoryOrderID=?''',(pid,))
        summary['deliverySuppliers']=', '.join(r['name'] for r in delivered) or 'No supplier deliveries recorded'
        summary['ingredients']=len(lines)
        summary['estimatedCost']=round(sum(r['unitCost']*r['quantityOrdered'] for r in lines),2) if lines and all(r['unitCost'] is not None for r in lines) else 'Not recorded for every line'
        invoices=self.rows('''SELECT a.transactionID,a.amount,a.reference FROM AccountingTransaction a
            JOIN InventoryTransaction t ON a.sourceType='Delivery' AND a.sourceID=t.transactionID
            WHERE t.inventoryOrderID=?''',(pid,))
        summary['recordedInvoices']=sum(r['amount'] for r in invoices) if invoices else 'Not recorded'
        return summary,lines,invoices

    def supplier(self,sid):
        rows=self.rows('SELECT * FROM Supplier WHERE supplierID=?',(sid,))
        if not rows:raise InventoryError('Supplier not found.')
        orders=self.rows('''SELECT DISTINCT io.* FROM InventoryOrder io LEFT JOIN InventoryTransaction t
            ON t.inventoryOrderID=io.inventoryOrderID WHERE io.supplierID=? OR t.supplierID=?''',(sid,sid))
        ingredients=self.rows('''SELECT i.* FROM InventoryItem i WHERE i.ingredientID IN
            (SELECT ingredientID FROM SupplierIngredient WHERE supplierID=? UNION
             SELECT ingredientID FROM InventoryTransaction WHERE supplierID=?) ORDER BY i.ingredientName''',(sid,sid))
        return {**rows[0],'totalPOs':len(orders)},orders,ingredients

    def set_catalogue(self,actor,sid,iid):
        with transaction(self.path) as db:
            user=db.execute('SELECT role,accountActive FROM "User" WHERE userID=?',(actor,)).fetchone()
            if not user or not user['accountActive'] or user['role'] not in ('Owner','Employee'):
                raise InventoryError('Active staff access required.')
            db.execute('INSERT OR IGNORE INTO SupplierIngredient VALUES(?,?)',(_ident(sid),_ident(iid)))

    def order(self,oid):
        svc=InventoryService(self.path);summary=svc.order_details(oid)
        staff=self.rows('''SELECT DISTINCT u.name FROM InventoryTransaction t JOIN "User" u ON u.userID=t.userID
            WHERE t.customerOrderID=? AND t.quantity<0''',(oid,))
        summary['completedBy']=', '.join(r['name'] for r in staff) if summary['status']=='Completed' and staff else 'Not recorded'
        loyalty=self.rows('SELECT * FROM LoyaltyTransaction WHERE orderID=?',(oid,))
        sales=self.rows("SELECT * FROM AccountingTransaction WHERE sourceType='Order' AND sourceID=?",(oid,))
        return summary,svc.order_recipes(oid),loyalty,sales

    def eligible_customers(self,rid):
        return self.rows('''SELECT u.userID,u.name,u.username,a.pointsBalance FROM Reward r
            JOIN LoyaltyAccount a ON a.pointsBalance>=r.pointsCost JOIN Customer c ON c.customerID=a.customerID
            JOIN "User" u ON u.userID=c.userID WHERE r.rewardID=? AND r.isActive=1
            AND a.status='Active' AND u.accountActive=1 AND u.role='Customer' ORDER BY u.userID''',(rid,))
