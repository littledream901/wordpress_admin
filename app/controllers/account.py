from app.core.crud import CRUDBase
from app.models.account import Account
from app.schemas.account import AccountCreate, AccountUpdate


class AccountController(CRUDBase[Account, AccountCreate, AccountUpdate]):
    def __init__(self):
        super().__init__(model=Account)


account_controller = AccountController()
