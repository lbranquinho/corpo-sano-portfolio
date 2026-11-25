"""Dados de referência (idempotente). Não cria clientes, serviços, preços ou alíquotas:
esses dados são da clínica e precisam ser informados por ela/contador."""
from __future__ import annotations

from datetime import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.permissions import DEFAULT_ROLES, PERMISSIONS
from app.core.security import hash_password, validate_password_strength
from app.models.auth import Permission, Role, User
from app.models.clinic import BusinessHour
from app.models.finance import CostCenter, FinancialAccount, FinancialCategory, PaymentMethod
from app.models.fiscal import TaxCompanySettings, TaxObligationTemplate
from app.models.system import Clinic

PAYMENT_METHODS = [
    ("dinheiro", "Dinheiro"),
    ("pix", "PIX"),
    ("cartao_debito", "Cartão de débito"),
    ("cartao_credito", "Cartão de crédito"),
    ("transferencia", "Transferência"),
    ("outros", "Outros"),
]

CATEGORIES = {
    "receita": ["Atendimentos", "Pacotes", "Outras receitas"],
    "despesa": [
        "Aluguel",
        "Água",
        "Energia",
        "Internet",
        "Materiais",
        "Produtos",
        "Equipamentos",
        "Manutenção",
        "Serviços terceirizados",
        "Honorários contábeis",
        "Tributos",
        "Tarifas bancárias e de cartão",
        "Outras despesas",
    ],
}

COST_CENTERS = ["Atendimento", "Administrativo", "Comercial"]

# Modelos INATIVOS: o contador ativa somente o que se aplica à clínica.
# Prazos são referências e devem ser confirmados pelo contador.
OBLIGATION_TEMPLATES = [
    ("PGDAS-D — apuração do Simples Nacional", "PGDAS-D", "mensal", 20, None, 1, ["simples_nacional"], False),
    ("DAS — Simples Nacional", "DAS", "mensal", 20, None, 1, ["simples_nacional"], False),
    ("DAS-MEI", "DAS-MEI", "mensal", 20, None, 1, ["mei"], False),
    ("DASN-SIMEI — declaração anual do MEI", "DASN-SIMEI", "anual", 31, 5, 0, ["mei"], False),
    ("DEFIS — declaração anual do Simples Nacional", "DEFIS", "anual", 31, 3, 0, ["simples_nacional"], False),
    ("DCTFWeb", "DCTFWEB", "mensal", 15, None, 1, ["simples_nacional", "lucro_presumido", "lucro_real"], True),
    ("eSocial — eventos periódicos", "ESOCIAL", "mensal", 15, None, 1, ["mei", "simples_nacional", "lucro_presumido", "lucro_real"], True),
    ("EFD-Reinf", "EFD-REINF", "mensal", 15, None, 1, ["simples_nacional", "lucro_presumido", "lucro_real"], False),
    ("ISS — recolhimento municipal", "ISS", "mensal", 10, None, 1, ["lucro_presumido", "lucro_real"], False),
    ("Obrigação municipal (declaração de serviços)", "MUNICIPAL", "mensal", 10, None, 1, ["simples_nacional", "lucro_presumido", "lucro_real"], False),
]


def seed_reference_data(db: Session) -> None:
    # Permissões
    existing = {p.code: p for p in db.scalars(select(Permission)).all()}
    for code, (module, desc) in PERMISSIONS.items():
        if code not in existing:
            p = Permission(code=code, module=module, description=desc)
            db.add(p)
            existing[code] = p
        else:
            existing[code].module, existing[code].description = module, desc
    db.flush()
    # Perfis padrão (só cria; personalizações posteriores são preservadas)
    for code, spec in DEFAULT_ROLES.items():
        role = db.scalar(select(Role).where(Role.code == code))
        if role is None:
            role = Role(code=code, name=spec["name"], description=spec["description"], is_system=True)
            role.permissions = [existing[c] for c in spec["permissions"]]
            db.add(role)
        elif code == "admin":
            role.permissions = [existing[c] for c in PERMISSIONS]  # admin sempre com acesso completo
    # Formas de pagamento
    have = set(db.scalars(select(PaymentMethod.code)).all())
    for code, name in PAYMENT_METHODS:
        if code not in have:
            db.add(PaymentMethod(code=code, name=name))
    # Categorias financeiras
    have_cat = {(c.name, c.kind) for c in db.scalars(select(FinancialCategory)).all()}
    for kind, names in CATEGORIES.items():
        for name in names:
            if (name, kind) not in have_cat:
                db.add(FinancialCategory(name=name, kind=kind))
    have_cc = set(db.scalars(select(CostCenter.name)).all())
    for name in COST_CENTERS:
        if name not in have_cc:
            db.add(CostCenter(name=name))
    if db.scalar(select(FinancialAccount).limit(1)) is None:
        db.add(FinancialAccount(name="Caixa da clínica", kind="caixa"))
    # Horário de funcionamento inicial (editável em Configurações > Agenda)
    if db.scalar(select(BusinessHour).limit(1)) is None:
        for wd in range(7):  # todos os dias, das 6h às 22h
            db.add(BusinessHour(weekday=wd, is_open=True, open_time=time(6), close_time=time(22)))
    if db.scalar(select(Clinic).limit(1)) is None:
        db.add(Clinic(name="Corpo Sano", trade_name="Corpo Sano", timezone=get_settings().timezone))
    if db.scalar(select(TaxCompanySettings).limit(1)) is None:
        db.add(TaxCompanySettings())
    if db.scalar(select(TaxObligationTemplate).limit(1)) is None:
        for name, code, freq, day, month, offset, regimes, needs_emp in OBLIGATION_TEMPLATES:
            db.add(
                TaxObligationTemplate(
                    name=name,
                    code=code,
                    frequency=freq,
                    due_day=day,
                    due_month=month,
                    reference_offset_months=offset,
                    applicable_regimes=regimes,
                    requires_employees=needs_emp,
                    is_active=False,
                    description="Prazo de referência: confirme com o contador antes de ativar.",
                )
            )
    db.flush()


def ensure_initial_admin(db: Session) -> User | None:
    """Cria o primeiro administrador a partir de INITIAL_ADMIN_* se não houver usuários."""
    s = get_settings()
    if db.scalar(select(User).limit(1)) is not None:
        return None
    if not s.initial_admin_email or not s.initial_admin_password:
        return None
    validate_password_strength(s.initial_admin_password)
    role = db.scalar(select(Role).where(Role.code == "admin"))
    user = User(
        name=s.initial_admin_name,
        email=s.initial_admin_email.lower().strip(),
        password_hash=hash_password(s.initial_admin_password),
        role_id=role.id,
        must_change_password=True,
    )
    db.add(user)
    db.flush()
    return user
