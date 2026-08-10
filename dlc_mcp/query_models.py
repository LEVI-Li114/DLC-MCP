from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class QueryRequest:
    table_name: str
    partition: dict[str, str]


@dataclass(frozen=True)
class ValidatedQuery:
    table_name: str
    partition: dict[str, str]
    sql: str
    sql_hash: str
    idempotency_key: str


@dataclass
class QueryJob:
    query_id: str
    table_name: str
    partition: dict[str, str]
    sql_hash: str
    idempotency_key: str
    status: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    external_task_id: str = ""
    submitted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result_expires_at: Optional[datetime] = None
    row_count: Optional[int] = None
    error_code: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class QueryStatusPatch:
    status: str
    updated_at: datetime
    completed_at: Optional[datetime] = None
    result_expires_at: Optional[datetime] = None
    row_count: Optional[int] = None
    error_code: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class ExternalTaskRef:
    task_id: str


@dataclass(frozen=True)
class ExternalStatus:
    status: str
    raw_state: int
    message: str = ""


@dataclass(frozen=True)
class CountResult:
    row_count: int
