from enum import StrEnum

from sqlalchemy import BigInteger, Boolean, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDMixin


class ProviderEnum(StrEnum):
    alpha = 'alpha'
    beta = 'beta'


class Model(Base, TimestampMixin):
    __tablename__ = 'models'

    slug: Mapped[str] = mapped_column(String(100), primary_key=True)
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)

    legs: Mapped[list['ModelLeg']] = relationship(
        back_populates='model',
        lazy='selectin',
        order_by='ModelLeg.priority',
    )


class ModelLeg(Base, UUIDMixin, TimestampMixin):
    __tablename__ = 'model_legs'

    model_slug: Mapped[str] = mapped_column(
        ForeignKey('models.slug', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    provider: Mapped[ProviderEnum] = mapped_column(Enum(ProviderEnum), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    max_ref_images: Mapped[int] = mapped_column(Integer, nullable=False)
    skip_on_moderation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    model: Mapped[Model] = relationship(back_populates='legs', lazy='selectin')

    __table_args__ = (UniqueConstraint('model_slug', 'provider', name='uq_model_leg_model_provider'),)
