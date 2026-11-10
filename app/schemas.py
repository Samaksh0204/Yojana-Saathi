from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Gender = Literal["male", "female", "other"]
Occupation = Literal[
    "farmer", "agri_labourer", "fisher", "street_vendor", "artisan",
    "construction_worker", "unorganised_worker", "self_employed", "salaried",
    "student", "unemployed", "homemaker", "other",
]
Education = Literal[
    "below_class_9", "class_9_10", "class_11_12", "diploma", "undergraduate", "postgraduate",
]
Caste = Literal["general", "obc", "sc", "st", "ews"]


class Child(BaseModel):
    gender: Optional[Gender] = None
    age: Optional[int] = None
    education: Optional[Education] = None


class UserProfile(BaseModel):
    """Everything we know about the person. None always means "not told yet"."""

    age: Optional[int] = None
    gender: Optional[Gender] = None
    state: Optional[str] = Field(None, description="Indian state or UT, full English name")
    residence: Optional[Literal["rural", "urban"]] = None
    occupation: Optional[Occupation] = None
    annual_income: Optional[int] = Field(None, description="Annual family income in rupees")
    caste: Optional[Caste] = None
    land_acres: Optional[float] = None
    owns_land: Optional[bool] = None
    bpl: Optional[bool] = Field(None, description="Has a BPL / Antyodaya / priority ration card")
    is_student: Optional[bool] = None
    education: Optional[Education] = Field(None, description="Level currently being studied")
    disability: Optional[bool] = None
    marital_status: Optional[Literal["single", "married", "widowed", "divorced"]] = None
    pregnant: Optional[bool] = Field(None, description="Pregnant or a lactating mother")
    minority: Optional[bool] = Field(None, description="Muslim, Christian, Sikh, Buddhist, Jain or Parsi")
    has_pucca_house: Optional[bool] = None
    is_govt_employee: Optional[bool] = None
    pays_income_tax: Optional[bool] = None
    children: list[Child] = Field(default_factory=list)

    def merged_with(self, update: "UserProfile") -> "UserProfile":
        """Newer non-empty answers overwrite older ones."""
        data = self.model_dump()
        for key, value in update.model_dump().items():
            if value is None or (key == "children" and not value):
                continue
            data[key] = value
        return UserProfile(**data)

    def known_fields(self) -> dict[str, Any]:
        return {k: v for k, v in self.model_dump().items() if v not in (None, [])}


class Scheme(BaseModel):
    id: str
    name: str
    name_hi: Optional[str] = None
    level: Literal["central", "state"]
    states: list[str] = Field(default_factory=list)  # empty = all India
    category: str
    benefit: str
    summary: str
    rules: dict[str, Any] = Field(default_factory=dict)
    child_only: bool = False  # claimed by a parent for a child (never matched against the user)
    note: Optional[str] = None
    documents: list[str] = Field(default_factory=list)
    url: str

    def as_text(self) -> str:
        parts = [self.name, self.name_hi or "", self.category, self.summary, self.benefit,
                 self.note or "", "Documents: " + ", ".join(self.documents),
                 "States: " + (", ".join(self.states) or "All India")]
        return "\n".join(p for p in parts if p)


class Match(BaseModel):
    scheme_id: str
    status: Literal["eligible", "possible"]
    beneficiary: str = "self"  # self | daughter | son | child
    passed: list[str] = Field(default_factory=list)  # rule keys that were satisfied
    missing: list[str] = Field(default_factory=list)  # profile fields still needed
