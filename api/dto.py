from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LoginRequest:
    username: str
    password: str


@dataclass
class SignupRequest:
    business_name: str
    email: str
    password: str


@dataclass
class ChangePasswordRequest:
    user_id: int
    current_password: str
    new_password: str


@dataclass
class AuthResponse:
    success: bool
    error: str = ""
    redirect_url: str = ""
    user_id: Optional[int] = None
    tenant_id: Optional[int] = None
    username: str = ""
    role: str = ""


@dataclass
class ChatRequest:
    question: str
    session_id: str
    tenant_id: int


@dataclass
class ChatResponse:
    success: bool
    answer: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    error: str = ""


@dataclass
class AdminLoginRequest:
    username: str
    password: str


@dataclass
class AdminLoginResponse:
    success: bool
    error: str = ""


@dataclass
class SettingsUpdateRequest:
    tenant_id: int
    bot_name: str = ""
    theme: str = "dark"
    language: str = "en"
    personality: str = ""
    tone: str = ""
    purpose: str = ""
    instructions: str = ""
    avatar_file: Optional[bytes] = None
    avatar_filename: str = ""


@dataclass
class UserInviteRequest:
    tenant_id: int
    email: str
    password: str = ""
    role: str = "viewer"


@dataclass
class UserEditRequest:
    user_id: int
    tenant_id: int
    role: str


@dataclass
class TenantCreateRequest:
    name: str


@dataclass
class TenantEditRequest:
    tenant_id: int
    name: str


@dataclass
class KnowledgeAddUrlRequest:
    tenant_id: int
    url: str


@dataclass
class KnowledgeUploadDocRequest:
    tenant_id: int
    filename: str
    file_data: bytes
    doc_type: str


@dataclass
class CuratorActionRequest:
    tenant_id: int
    item_id: int
    action: str
