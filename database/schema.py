from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

# Base schemas
class UserBase(BaseModel):
    telegram_id: int
    username: Optional[str] = None
    first_name: str
    is_admin: bool = False

class UserCreate(UserBase):
    pass

class User(UserBase):
    id: int
    
    class Config:
        from_attributes = True

class EventBase(BaseModel):
    title: str
    description: Optional[str] = None
    registration_end: datetime
    shipping_deadline: datetime
    budget: Optional[int] = None
    group_chat_id: Optional[int] = None

class EventCreate(EventBase):
    pass

class Event(EventBase):
    id: int
    status: str
    created_at: datetime
    
    class Config:
        from_attributes = True

class ParticipantBase(BaseModel):
    event_id: int
    telegram_id: int
    username: Optional[str] = None
    first_name: str
    wishes: Optional[str] = None
    address: Optional[str] = None
    delivery_methods: Optional[str] = None
    is_active: bool = True

class ParticipantCreate(ParticipantBase):
    pass

class Participant(ParticipantBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class SantaPairBase(BaseModel):
    event_id: int
    santa_id: int
    receiver_id: int
    is_gift_sent: bool = False
    gift_sent_at: Optional[datetime] = None

class SantaPairCreate(SantaPairBase):
    pass

class SantaPair(SantaPairBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

# Response schemas
class StatusResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
