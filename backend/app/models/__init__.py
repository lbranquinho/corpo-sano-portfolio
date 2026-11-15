"""Importa todos os modelos para registro no metadata (Alembic e relacionamentos)."""
from app.models.base import Base  # noqa: F401
from app.models.auth import Permission, Role, User, UserPermission, UserSession, role_permissions  # noqa: F401
from app.models.system import AuditLog, BackupHistory, Clinic, StoredFile, SystemSetting  # noqa: F401
from app.models.clinic import (  # noqa: F401
    BusinessHour,
    Holiday,
    Professional,
    ProfessionalAvailability,
    Room,
    ScheduleBlock,
)
from app.models.customer import Customer, CustomerConsent  # noqa: F401
from app.models.catalog import PackagePlan, Service, ServiceCategory, TaxServiceCode, service_professionals  # noqa: F401
from app.models.schedule import Appointment, AppointmentStatusHistory  # noqa: F401
from app.models.package import Package, PackageSession  # noqa: F401
from app.models.clinical import CustomerHealthRecord, Treatment, TreatmentRecord  # noqa: F401
from app.models.crm import CrmCampaign, CrmInteraction, CrmLead, CrmTask  # noqa: F401
from app.models.whatsapp import WhatsappMessage, WhatsappTemplate  # noqa: F401
from app.models.finance import (  # noqa: F401
    AccountsPayable,
    AccountsReceivable,
    CashClosing,
    CostCenter,
    Expense,
    FinancialAccount,
    FinancialCategory,
    FinancialTransaction,
    PaymentMethod,
)
from app.models.fiscal import (  # noqa: F401
    AccountingExport,
    DigitalCertificate,
    FiscalDocument,
    FiscalInvoice,
    FiscalInvoiceEvent,
    TaxAssessment,
    TaxCompanySettings,
    TaxObligation,
    TaxObligationTemplate,
    TaxRate,
)
